from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager, closing
from urllib.parse import urlsplit

import anyio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from .common import AppError, canonical
from .domain.engine import RULE_CODES, suggest_types, validate_configuration
from .domain.errors import DomainError
from .manager import Manager
from .reports import csv_stream, issues_page, iter_issues, require_success, results_db
from .schemas import (
    IDEMPOTENCY_HEADERS_OPENAPI,
    UPLOAD_OPENAPI,
    WRITE_HEADERS_OPENAPI,
    Capabilities,
    Dataset,
    DatasetSummary,
    DuplicateGroupPage,
    ErrorEnvelope,
    Health,
    Issue,
    Page,
    PostDatasetReceipt,
    PostRunReceipt,
    RawRecord,
    RecordWithIssues,
    Report,
    Run,
    TypeSuggestions,
)
from .settings import Settings
from .uploads import receive_upload

logger = logging.getLogger("dataset_check")


def error_body(exc, request_id):
    return {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
            "request_id": request_id,
        }
    }


class GuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request, call_next):
        request.state.request_id = str(uuid.uuid4())
        try:
            host = urlsplit("//" + request.headers.get("host", "")).hostname
            if host not in self.settings.allowed_hosts:
                raise AppError("ORIGIN_NOT_ALLOWED", "Invalid Host header", 403)
            if request.url.path.startswith("/api/"):
                origin = request.headers.get("origin")
                if origin and origin not in self.settings.allowed_origins:
                    raise AppError("ORIGIN_NOT_ALLOWED", "This request origin is not allowed", 403)
                if (
                    request.method in {"POST", "PUT", "PATCH", "DELETE"}
                    and request.headers.get("x-dataset-check") != "1"
                ):
                    raise AppError(
                        "REQUEST_GUARD_REQUIRED", "The X-Dataset-Check: 1 header is required", 403
                    )
            response = await call_next(request)
        except AppError as exc:
            response = JSONResponse(
                error_body(exc, request.state.request_id),
                status_code=exc.status,
                headers=exc.headers,
            )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


def create_app(settings=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application):
        application.state.manager = None
        try:
            application.state.manager = Manager(settings)
        except Exception:
            logger.error("catalog_startup_failed")
        yield
        if application.state.manager:
            application.state.manager.close()

    application = FastAPI(
        title="Dataset Check",
        version="1.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        responses={
            code: {"model": ErrorEnvelope}
            for code in (400, 403, 404, 408, 409, 413, 415, 422, 429, 500, 503, 504, 507)
        },
    )
    application.state.settings = settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Dataset-Check", "Idempotency-Key"],
        expose_headers=["Location", "Idempotency-Replayed", "Retry-After", "Server-Timing"],
    )
    application.add_middleware(GuardMiddleware, settings=settings)

    @application.exception_handler(AppError)
    async def app_error(request, exc):
        return JSONResponse(
            error_body(exc, request.state.request_id), status_code=exc.status, headers=exc.headers
        )

    @application.exception_handler(DomainError)
    async def domain_error(request, exc):
        status = (
            422 if exc.code in {"RULE_CONFIG_INVALID", "QUERY_INVALID", "REQUEST_INVALID"} else 400
        )
        return JSONResponse(
            error_body(
                AppError(exc.code, exc.message, status, exc.details), request.state.request_id
            ),
            status_code=status,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        details = [
            {"field": ".".join(map(str, e["loc"])), "reason": e["type"]} for e in exc.errors()
        ]
        error = AppError("QUERY_INVALID", "Invalid query parameters", 422, details)
        return JSONResponse(error_body(error, request.state.request_id), status_code=422)

    @application.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            error_body(
                AppError(
                    "NOT_FOUND" if exc.status_code == 404 else "REQUEST_INVALID",
                    "Resource not found" if exc.status_code == 404 else "Request not supported",
                    exc.status_code,
                ),
                request.state.request_id,
            ),
            status_code=exc.status_code,
        )

    @application.exception_handler(Exception)
    async def internal_error(request, exc):
        logger.error(
            "request_failed request_id=%s type=%s", request.state.request_id, type(exc).__name__
        )
        code, status = (
            ("TEMP_STORAGE_UNAVAILABLE", 507)
            if isinstance(exc, (sqlite3.Error, OSError))
            else ("INTERNAL_ERROR", 500)
        )
        return JSONResponse(
            error_body(
                AppError(code, "Could not complete the request", status), request.state.request_id
            ),
            status_code=status,
        )

    def manager(request):
        value = request.app.state.manager
        if value is None:
            raise AppError(
                "SERVICE_UNAVAILABLE",
                "The data directory is unavailable. Check the settings and restart the application.",
                503,
            )
        return value

    def page(request):
        try:
            offset = int(request.query_params.get("offset", 0))
            limit = int(request.query_params.get("limit", settings.limits["default_page_size"]))
        except ValueError:
            raise AppError("QUERY_INVALID", "Page parameters must be integers", 422) from None
        if offset < 0 or not 1 <= limit <= settings.limits["max_page_size"]:
            raise AppError("QUERY_INVALID", "Invalid page size or offset", 422)
        return offset, limit

    def key_for(request):
        try:
            key = str(uuid.UUID(request.headers.get("idempotency-key", "")))
        except (ValueError, AttributeError):
            raise AppError("REQUEST_INVALID", "Idempotency-Key must contain a UUID", 422) from None
        return f"{request.method}:{request.url.path}", key

    def replay(store, row, fingerprint):
        if row["state"] == "processing":
            raise AppError(
                "IDEMPOTENCY_IN_PROGRESS",
                "This request is still being processed",
                409,
                headers={"Retry-After": "1"},
            )
        if row["fingerprint"] is not None and row["fingerprint"] != fingerprint:
            raise AppError(
                "IDEMPOTENCY_KEY_REUSED",
                "This key has already been used with different content",
                409,
            )
        if row["state"] == "gone":
            raise AppError(
                "IDEMPOTENCY_RESOURCE_GONE",
                "The resource was deleted or expired. Use a new key for a new action.",
                404,
            )
        if row["state"] == "done":
            try:
                if row["resource_type"] == "dataset":
                    store.dataset(row["resource_id"])
                else:
                    store.run(row["resource_id"])
            except AppError:
                raise AppError(
                    "IDEMPOTENCY_RESOURCE_GONE", "The resource was deleted or expired", 404
                ) from None
        headers = {"Idempotency-Replayed": "true"}
        if row["location"]:
            headers["Location"] = row["location"]
        return JSONResponse(
            json.loads(row["response"]), status_code=row["http_status"], headers=headers
        )

    @application.get("/api/v1/health", response_model=Health)
    def health(request: Request):
        return JSONResponse(
            {"status": "ok" if request.app.state.manager else "unavailable"},
            status_code=200 if request.app.state.manager else 503,
        )

    @application.get("/api/v1/capabilities", response_model=Capabilities)
    def capabilities():
        return settings.capabilities()

    @application.get("/api/v1/datasets", response_model=Page[DatasetSummary])
    def datasets(request: Request):
        return manager(request).store.list_datasets(*page(request))

    @application.post(
        "/api/v1/datasets",
        response_model=PostDatasetReceipt,
        status_code=201,
        openapi_extra=UPLOAD_OPENAPI,
    )
    async def upload(request: Request):
        service = manager(request)
        store = service.store
        scope, key = key_for(request)
        previous = store.request(scope, key)
        if previous and previous["state"] == "processing":
            return replay(store, previous, None)
        acquired, accepted, published = False, False, False
        folder = store.root / "staging" / str(uuid.uuid4())
        destination = None
        try:
            if not previous:
                service.acquire()
                acquired = True
                store.cleanup()
                if store.list_datasets(0, 1)["total"] >= settings.limits["max_datasets"]:
                    raise AppError(
                        "DATASET_LIMIT_REACHED",
                        "The dataset limit has been reached. Delete an unused dataset.",
                        409,
                    )
                store.begin_request(scope, key)
            store.check_space(65536)
            folder.mkdir()
            data = await receive_upload(request, folder, settings, store)
            fingerprint = hashlib.sha256(
                canonical(
                    {k: data[k] for k in ("filename", "sha256", "encoding", "delimiter")}
                ).encode()
            ).hexdigest()
            if previous:
                return replay(store, previous, fingerprint)
            store.fingerprint_request(scope, key, fingerprint)
            accepted = True
            started = time.monotonic()
            result = await anyio.to_thread.run_sync(
                lambda: service.execute(
                    data | {"kind": "import", "folder": str(folder)},
                    settings.limits["import_timeout_seconds"],
                )
            )
            resource_id = str(uuid.uuid4())
            receipt = {"dataset_id": resource_id, "dataset_url": f"/api/v1/datasets/{resource_id}"}
            store.check_space()
            destination = store.root / "datasets" / resource_id
            folder.rename(destination)
            store.publish_dataset(resource_id, result["metadata"], scope, key, receipt)
            published = True
            return JSONResponse(
                receipt,
                status_code=201,
                headers={
                    "Location": receipt["dataset_url"],
                    "Server-Timing": f"import;dur={(time.monotonic() - started) * 1000:.3f}",
                },
            )
        except (AppError, OSError, sqlite3.Error) as failure:
            exc = (
                failure
                if isinstance(failure, AppError)
                else AppError(
                    "TEMP_STORAGE_UNAVAILABLE", "Could not save the imported dataset", 507
                )
            )
            if accepted and not published:
                store.fail_request(
                    scope, key, exc.status, error_body(exc, request.state.request_id)
                )
            raise exc
        finally:
            try:
                if not previous and not accepted:
                    store.drop_processing_request(scope, key)
            finally:
                try:
                    try:
                        store.remove_tree(folder)
                    finally:
                        if destination is not None and not published:
                            store.remove_tree(destination)
                finally:
                    if acquired:
                        service.release()

    @application.get("/api/v1/datasets/{dataset_id}", response_model=Dataset)
    def dataset(request: Request, dataset_id: str):
        return manager(request).store.dataset(dataset_id)

    @application.get("/api/v1/datasets/{dataset_id}/rows", response_model=Page[RawRecord])
    def rows(request: Request, dataset_id: str):
        store = manager(request).store
        offset, limit = page(request)
        with store.lock:
            info = store.dataset(dataset_id)
            return {
                "items": store.records(dataset_id, offset, limit),
                "total": info["row_count"],
                "offset": offset,
                "limit": limit,
            }

    @application.get(
        "/api/v1/datasets/{dataset_id}/type-suggestions", response_model=TypeSuggestions
    )
    def suggestions(request: Request, dataset_id: str, decimal_separator: str = "."):
        store = manager(request).store
        with store.lock:
            info = store.dataset(dataset_id)
            # Sample the first 1,000 non-empty values per column, not merely 1,000 rows.
            sampled = [[] for _ in info["columns"]]
            path = store.root / "datasets" / dataset_id / "records.sqlite"
            with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as db:
                for row in db.execute("SELECT values_json FROM records ORDER BY row_index"):
                    values = json.loads(row[0])
                    for index, value in enumerate(values):
                        if value.strip() and len(sampled[index]) < 1000:
                            sampled[index].append(value)
                    if all(len(values) >= 1000 for values in sampled):
                        break
            count = max(map(len, sampled), default=0)
            sample_rows = [
                [values[i] if i < len(values) else "" for values in sampled] for i in range(count)
            ]
            return suggest_types(sample_rows, info["columns"], decimal_separator)

    @application.delete(
        "/api/v1/datasets/{dataset_id}",
        status_code=204,
        openapi_extra={"parameters": WRITE_HEADERS_OPENAPI},
    )
    def delete_dataset(request: Request, dataset_id: str):
        manager(request).store.delete_dataset(dataset_id)

    @application.post(
        "/api/v1/datasets/{dataset_id}/runs",
        response_model=PostRunReceipt,
        status_code=202,
        openapi_extra={
            "parameters": IDEMPOTENCY_HEADERS_OPENAPI,
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/Configuration"}}
                },
            },
        },
    )
    async def start_run(request: Request, dataset_id: str):
        service = manager(request)
        store = service.store
        scope, key = key_for(request)
        previous = store.request(scope, key)
        if previous and previous["state"] == "processing":
            return replay(store, previous, None)
        try:
            body = await request.body()
            if len(body) > 262144:
                raise AppError("REQUEST_INVALID", "The configuration is too large", 422)
            configuration = json.loads(body)
        except (ValueError, UnicodeError):
            raise AppError("REQUEST_INVALID", "Expected a JSON configuration", 422) from None
        # Deleted resources must not be silently re-created by a retry.
        if previous:
            # Validate the shape without requiring the resource to still exist.
            # Normalization (for example an omitted upper bound -> null) must
            # be identical on initial acceptance and on a later replay.
            candidate_columns = (
                [
                    {"column_id": rule.get("column_id")}
                    for rule in configuration.get("columns", [])
                    if isinstance(rule, dict) and isinstance(rule.get("column_id"), str)
                ]
                if isinstance(configuration, dict)
                and isinstance(configuration.get("columns"), list)
                else []
            )
            normalized = validate_configuration(configuration, candidate_columns)
            fingerprint = hashlib.sha256(canonical(normalized).encode()).hexdigest()
            return replay(store, previous, fingerprint)
        dataset = store.dataset(dataset_id)
        configuration = validate_configuration(configuration, dataset["columns"])
        if not dataset["row_count"]:
            raise AppError("EMPTY_DATASET", "The dataset contains no records", 409)
        fingerprint = hashlib.sha256(canonical(configuration).encode()).hexdigest()
        service.acquire()
        handed_to_worker = False
        try:
            if len(dataset["runs"]) >= settings.limits["max_runs_per_dataset"]:
                raise AppError(
                    "RUN_LIMIT_REACHED",
                    "The run limit has been reached. Delete an unused run.",
                    409,
                )
            store.begin_request(scope, key)
            store.fingerprint_request(scope, key, fingerprint)
            run_id = str(uuid.uuid4())
            receipt = {
                "run_id": run_id,
                "dataset_id": dataset_id,
                "status": "queued",
                "status_url": f"/api/v1/runs/{run_id}",
            }
            store.publish_run(run_id, dataset_id, configuration, scope, key, receipt)
            try:
                service.start_run(run_id, dataset, configuration)
            except Exception as exc:
                error = {
                    "code": exc.code if isinstance(exc, AppError) else "INTERNAL_ERROR",
                    "message": "Could not start the worker. Create a new validation run.",
                    "details": {},
                }
                try:
                    store.update_run(
                        run_id, status="failed", stage="failed", finished=time.time(), error=error
                    )
                finally:
                    try:
                        store.pin(dataset_id, -1)
                    finally:
                        store.remove_tree(store.root / "staging" / run_id)
            else:
                handed_to_worker = True
        except BaseException:
            store.drop_processing_request(scope, key)
            raise
        finally:
            if not handed_to_worker:
                service.release()
        return JSONResponse(receipt, status_code=202, headers={"Location": receipt["status_url"]})

    @application.get("/api/v1/runs/{run_id}", response_model=Run)
    def run(request: Request, run_id: str):
        return manager(request).store.run(run_id)

    @application.delete(
        "/api/v1/runs/{run_id}",
        status_code=204,
        openapi_extra={"parameters": WRITE_HEADERS_OPENAPI},
    )
    def delete_run(request: Request, run_id: str):
        manager(request).store.delete_run(run_id)

    @application.get("/api/v1/runs/{run_id}/issues", response_model=Page[Issue])
    def issues(
        request: Request,
        run_id: str,
        rule_code: str | None = None,
        column_id: str | None = None,
        row_index: int | None = None,
    ):
        store = manager(request).store
        with store.lock:
            info, dataset = require_success(store, run_id)
            if rule_code is not None and rule_code not in RULE_CODES:
                raise AppError("QUERY_INVALID", "Unknown rule code", 422)
            if column_id is not None and column_id not in {
                "__row__",
                *(c["column_id"] for c in dataset["columns"]),
            }:
                raise AppError("QUERY_INVALID", "Unknown column", 422)
            if row_index is not None and not 1 <= row_index <= dataset["row_count"]:
                raise AppError("QUERY_INVALID", "The record number is outside the dataset", 422)
            return issues_page(
                store,
                info,
                dataset,
                {"rule_code": rule_code, "column_id": column_id, "row_index": row_index},
                *page(request),
            )

    @application.get("/api/v1/runs/{run_id}/records/{row_index}", response_model=RecordWithIssues)
    def record(request: Request, run_id: str, row_index: int):
        store = manager(request).store
        with store.lock:
            info, dataset = require_success(store, run_id)
            value = store.record(dataset["dataset_id"], row_index)
            items = list(iter_issues(store, info, dataset, {"row_index": row_index}))
            return value | {"run_id": run_id, "issues": items, "violation_count": len(items)}

    @application.get("/api/v1/runs/{run_id}/groups/{group_id}", response_model=DuplicateGroupPage)
    def group(request: Request, run_id: str, group_id: str):
        store = manager(request).store
        with store.lock:
            info, dataset = require_success(store, run_id)
            offset, limit = page(request)
            with results_db(store, run_id) as db:
                row = db.execute(
                    "SELECT metadata FROM groups WHERE group_id=?", (group_id,)
                ).fetchone()
                if not row:
                    raise AppError("GROUP_NOT_FOUND", "Group not found", 404)
                indices = [
                    r[0]
                    for r in db.execute(
                        "SELECT row_index FROM members WHERE group_id=? ORDER BY row_index LIMIT ? OFFSET ?",
                        (group_id, limit, offset),
                    )
                ]
                result = json.loads(row[0])
            return result | {
                "items": [store.record(dataset["dataset_id"], i) for i in indices],
                "total": result["participant_count"],
                "offset": offset,
                "limit": limit,
            }

    @application.get(
        "/api/v1/runs/{run_id}/exports/{format}",
        responses={
            200: {
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/Report"}},
                    "text/csv": {"schema": {"type": "string", "format": "binary"}},
                }
            }
        },
    )
    def export(request: Request, run_id: str, format: str):
        if format not in {"report-json", "violations-csv", "problematic-records-csv"}:
            raise AppError("QUERY_INVALID", "Unknown export format", 422)
        store = manager(request).store
        with store.lock:
            info, dataset = require_success(store, run_id)
            store.pin_export(run_id, 1)
        release_lock = threading.Lock()
        released = False

        def release():
            nonlocal released
            with release_lock:
                if not released:
                    store.pin_export(run_id, -1)
                    released = True

        names = {
            "report-json": "report.json",
            "violations-csv": "violations.csv",
            "problematic-records-csv": "problematic_records.csv",
        }
        headers = {
            "Content-Disposition": f'attachment; filename="{names[format]}"',
            "Cache-Control": "no-store",
        }

        def stream():
            try:
                if format == "report-json":
                    with (store.root / "runs" / run_id / "report.json").open("rb") as source:
                        while chunk := source.read(65536):
                            yield chunk
                else:
                    yield from csv_stream(store, info, dataset, format)
            finally:
                release()

        if format == "report-json":
            headers["Content-Length"] = str(
                (store.root / "runs" / run_id / "report.json").stat().st_size
            )
        return StreamingResponse(
            stream(),
            media_type="application/json" if format == "report-json" else "text/csv; charset=utf-8",
            headers=headers,
            background=BackgroundTask(release),
        )

    @application.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            raise AppError("NOT_FOUND", "API endpoint not found", 404)
        target = (settings.frontend_dist / path).resolve()
        if not target.is_relative_to(settings.frontend_dist):
            raise AppError("NOT_FOUND", "Resource not found", 404)
        if target.is_file():
            return FileResponse(target)
        index = settings.frontend_dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(
            {
                "message": "The frontend has not been built yet. Run pnpm --dir frontend build or open Vite at localhost:5173.",
                "api_docs": "/api/docs",
            },
            status_code=503,
        )

    original_openapi = application.openapi

    def documented_openapi():
        if application.openapi_schema:
            return application.openapi_schema
        schema = original_openapi()
        report_schema = Report.model_json_schema(ref_template="#/components/schemas/{model}")
        definitions = report_schema.pop("$defs", {})
        schema.setdefault("components", {}).setdefault("schemas", {}).update(definitions)
        schema["components"]["schemas"]["Report"] = report_schema
        application.openapi_schema = schema
        return schema

    application.openapi = documented_openapi
    return application


app = create_app()
