"""API integration tests use real spawned workers and the persistent catalogue."""

import asyncio
import copy
import csv
import io
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import pytest
import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.common import AppError
from app.settings import Settings

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "synthetic"
ACCEPTANCE = (EXAMPLES / "acceptance.csv").read_bytes()
RULES = json.loads((EXAMPLES / "rules.json").read_text("utf-8"))
API = "/api/v1"


def headers(key=None):
    return {"X-Dataset-Check": "1", "Idempotency-Key": key or str(uuid.uuid4())}


def settings_for(path, **limits):
    return Settings(data_dir=path, allowed_hosts=("testserver",), limits=limits)


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as connection:
        assert connection.get(f"{API}/health").json() == {"status": "ok"}
        yield connection


def upload(client, data=ACCEPTANCE, key=None, filename="acceptance.csv", parameters=None):
    response = client.post(
        f"{API}/datasets",
        files={"file": (filename, data, "text/csv")},
        data=parameters or {},
        headers=headers(key),
    )
    assert response.status_code == 201, response.text
    return response


def wait_run(client, run_id):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        response = client.get(f"{API}/runs/{run_id}")
        assert response.status_code == 200, response.text
        run = response.json()
        if run["status"] in {"succeeded", "failed"}:
            # Publication precedes coordinator cleanup by a few instructions.
            while client.app.state.manager.gate.locked() and time.monotonic() < deadline:
                time.sleep(0.01)
            return run
        time.sleep(0.02)
    pytest.fail("Spawned worker did not finish within 25 seconds")


def start(client, dataset_id, config=RULES, key=None):
    response = client.post(f"{API}/datasets/{dataset_id}/runs", json=config, headers=headers(key))
    assert response.status_code == 202, response.text
    return response


@pytest.fixture
def control(client):
    dataset_id = upload(client).json()["dataset_id"]
    run_id = start(client, dataset_id).json()["run_id"]
    run = wait_run(client, run_id)
    assert run["status"] == "succeeded", run
    return client, dataset_id, run_id


def test_control_flow_profiles_and_exact_report(control):
    connection, dataset_id, run_id = control
    dataset = connection.get(f"{API}/datasets/{dataset_id}").json()
    assert (dataset["row_count"], dataset["column_count"]) == (9, 4)
    assert len(dataset["file_sha256"]) == 64
    assert [item["missing_count"] for item in dataset["profile"]] == [1, 1, 1, 1]
    assert dataset["csv"] == {"encoding": "utf-8", "delimiter": ","}
    run = connection.get(f"{API}/runs/{run_id}").json()
    assert run["configuration_snapshot"] == RULES
    assert run["algorithm_version"] == "1.0.0"
    assert run["error"] is None and run["stage"] == "completed"
    summary = run["summary"]
    assert (
        summary["total_records"],
        summary["total_issues"],
        summary["problematic_records"],
        summary["clean_records"],
    ) == (9, 13, 8, 1)
    assert [item["issue_count"] for item in summary["by_rule"]] == [3, 3, 1, 4, 2]
    response = connection.get(f"{API}/runs/{run_id}/exports/report-json")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert 'filename="report.json"' in response.headers["content-disposition"]
    report = response.json()
    assert set(report) == {
        "report_schema_version",
        "algorithm_version",
        "dataset",
        "columns",
        "configuration_snapshot",
        "run",
        "profile",
        "summary",
        "duplicate_groups",
        "issues",
        "problematic_records",
    }
    assert report["report_schema_version"] == "1.1"
    assert report["summary"] == summary
    assert len(report["issues"]) == 13
    assert [item["row_index"] for item in report["problematic_records"]] == list(range(1, 9))
    assert sum(item["violation_count"] for item in report["problematic_records"]) == 13
    assert report["problematic_records"][7]["values"][2] == "  "
    assert all(len(item["values"]) == 4 for item in report["problematic_records"])


def test_pagination_filters_groups_and_record_details(control):
    connection, dataset_id, run_id = control
    rows = connection.get(
        f"{API}/datasets/{dataset_id}/rows", params={"offset": 7, "limit": 1}
    ).json()
    assert rows["total"] == 9 and rows["items"][0]["row_index"] == 8
    outside = connection.get(f"{API}/datasets/{dataset_id}/rows", params={"offset": 99}).json()
    assert outside["items"] == [] and outside["total"] == 9
    issues = connection.get(f"{API}/runs/{run_id}/issues", params={"limit": 2, "offset": 1}).json()
    assert issues["total"] == 13 and len(issues["items"]) == 2
    assert issues["items"][0]["rule_code"] == "DUPLICATE_ROW"
    filtered = connection.get(
        f"{API}/runs/{run_id}/issues",
        params={"rule_code": "NON_UNIQUE_VALUE", "column_id": "c1", "row_index": 2},
    ).json()
    assert filtered["total"] == 1
    item = filtered["items"][0]
    group = connection.get(
        f"{API}/runs/{run_id}/groups/{item['duplicate_group_id']}", params={"offset": 1, "limit": 1}
    ).json()
    assert group["total"] == 2 and group["participant_count"] == 2
    assert group["normalized_key"] == "B"
    assert [item["row_index"] for item in group["items"]] == [3]
    row_level = connection.get(
        f"{API}/runs/{run_id}/issues", params={"column_id": "__row__"}
    ).json()
    assert row_level["total"] == 2
    assert all(item["column_id"] is None for item in row_level["items"])
    record = connection.get(f"{API}/runs/{run_id}/records/2").json()
    assert record["values"] == ["B", "", "5", "2024-02-30"]
    assert record["violation_count"] == len(record["issues"]) == 3
    assert connection.get(f"{API}/runs/{run_id}/groups/absent").status_code == 404


@pytest.mark.parametrize(
    "query",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"row_index": 0},
        {"column_id": "c999"},
        {"rule_code": "made_up"},
        {"row_index": "not-a-number"},
    ],
)
def test_query_validation(control, query):
    connection, _, run_id = control
    response = connection.get(f"{API}/runs/{run_id}/issues", params=query)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "QUERY_INVALID"


def test_exports_guard_csv_preserve_json_and_survive_source_deletion(client):
    values = ["", "-55", "=1+1", " \t ", "'original", "\ufeff  ＝1+1", "\tplain"]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["missing", "negative", "formula", "spaces", "apostrophe", "wide", "tab"])
    writer.writerow(values)
    dataset_id = upload(client, stream.getvalue().encode()).json()["dataset_id"]
    config = {
        "schema_version": "1.0",
        "decimal_separator": ".",
        "check_duplicate_rows": False,
        "columns": [
            {
                "column_id": f"c{i}",
                "required": i == 1,
                "unique": False,
                "expected_type": "text",
                "range": None,
            }
            for i in range(1, 8)
        ],
    }
    run_id = start(client, dataset_id, config).json()["run_id"]
    assert wait_run(client, run_id)["status"] == "succeeded"
    json_report = client.get(f"{API}/runs/{run_id}/exports/report-json").json()
    assert json_report["problematic_records"][0]["values"] == values
    csv_response = client.get(f"{API}/runs/{run_id}/exports/problematic-records-csv")
    assert csv_response.content.startswith(b"\xef\xbb\xbf")
    exported = list(csv.reader(io.StringIO(csv_response.content.decode("utf-8-sig"), newline="")))
    assert exported[1][3:] == [
        "",
        "'-55",
        "'=1+1",
        " \t ",
        "'original",
        "'\ufeff  ＝1+1",
        "'\tplain",
    ]
    assert exported[0][:3] == ["dq_record_number", "dq_violation_count", "dq_rule_codes"]
    violations = client.get(f"{API}/runs/{run_id}/exports/violations-csv")
    assert len(list(csv.reader(io.StringIO(violations.content.decode("utf-8-sig"))))) == 2
    assert client.delete(f"{API}/datasets/{dataset_id}", headers=headers()).status_code == 204
    assert json_report["problematic_records"][0]["values"] == values
    assert client.get(f"{API}/runs/{run_id}").status_code == 404


def test_idempotency_import_run_conflict_and_deleted_resource(client):
    import_key = str(uuid.uuid4())
    first = upload(client, key=import_key)
    dataset_id = first.json()["dataset_id"]
    second = upload(client, key=import_key)
    assert second.json() == first.json()
    assert second.headers["idempotency-replayed"] == "true"
    assert client.get(f"{API}/datasets").json()["total"] == 1
    conflict = client.post(
        f"{API}/datasets",
        files={"file": ("acceptance.csv", ACCEPTANCE + b"\n", "text/csv")},
        headers=headers(import_key),
    )
    assert (
        conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    )
    run_key = str(uuid.uuid4())
    first_run = start(client, dataset_id, key=run_key)
    run_id = first_run.json()["run_id"]
    assert wait_run(client, run_id)["status"] == "succeeded"
    replay = start(client, dataset_id, key=run_key)
    assert replay.json() == first_run.json() and replay.headers["idempotency-replayed"] == "true"
    changed = copy.deepcopy(RULES)
    changed["check_duplicate_rows"] = False
    conflict = client.post(
        f"{API}/datasets/{dataset_id}/runs", json=changed, headers=headers(run_key)
    )
    assert (
        conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    )
    assert client.delete(f"{API}/runs/{run_id}", headers=headers()).status_code == 204
    gone = client.post(f"{API}/datasets/{dataset_id}/runs", json=RULES, headers=headers(run_key))
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "IDEMPOTENCY_RESOURCE_GONE"
    assert client.delete(f"{API}/datasets/{dataset_id}", headers=headers()).status_code == 204
    gone = client.post(
        f"{API}/datasets",
        files={"file": ("acceptance.csv", ACCEPTANCE, "text/csv")},
        headers=headers(import_key),
    )
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "IDEMPOTENCY_RESOURCE_GONE"


def test_idempotency_uses_validated_single_bound_configuration(client):
    dataset_id = upload(client).json()["dataset_id"]
    config = copy.deepcopy(RULES)
    config["columns"][2]["range"] = {"min": "0"}
    key = str(uuid.uuid4())
    first = start(client, dataset_id, config, key)
    run_id = first.json()["run_id"]
    wait_run(client, run_id)
    replay = start(client, dataset_id, config, key)
    assert replay.json() == first.json()


def test_persistent_snapshot_results_and_replays_after_restart(tmp_path):
    config = settings_for(tmp_path)
    import_key, run_key = str(uuid.uuid4()), str(uuid.uuid4())
    with TestClient(create_app(config)) as connection:
        dataset_id = upload(connection, key=import_key).json()["dataset_id"]
        run_id = start(connection, dataset_id, key=run_key).json()["run_id"]
        before = wait_run(connection, run_id)
        report = connection.get(f"{API}/runs/{run_id}/exports/report-json").content
    with TestClient(create_app(config)) as connection:
        assert connection.get(f"{API}/health").status_code == 200
        assert connection.get(f"{API}/datasets").json()["items"][0]["dataset_id"] == dataset_id
        restored = connection.get(f"{API}/runs/{run_id}").json()
        assert restored["configuration_snapshot"] == RULES
        assert restored["summary"] == before["summary"]
        assert connection.get(f"{API}/runs/{run_id}/exports/report-json").content == report
        assert upload(connection, key=import_key).json()["dataset_id"] == dataset_id
        assert start(connection, dataset_id, key=run_key).json()["run_id"] == run_id


def test_registry_deletion_frees_capacity(client):
    ids = [upload(client).json()["dataset_id"] for _ in range(3)]
    listing = client.get(f"{API}/datasets", params={"offset": 1, "limit": 1}).json()
    assert listing["total"] == 3 and len(listing["items"]) == 1
    blocked = client.post(
        f"{API}/datasets", files={"file": ("more.csv", ACCEPTANCE)}, headers=headers()
    )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "DATASET_LIMIT_REACHED"
    assert client.delete(f"{API}/datasets/{ids[0]}", headers=headers()).status_code == 204
    assert client.get(f"{API}/datasets/{ids[0]}").status_code == 404
    assert upload(client).status_code == 201
    assert client.get(f"{API}/datasets").json()["total"] == 3


def test_result_budget_failure_exposes_no_partial_results(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, max_issues_per_run=2))) as connection:
        dataset_id = upload(connection).json()["dataset_id"]
        run_id = start(connection, dataset_id).json()["run_id"]
        run = wait_run(connection, run_id)
        assert run["status"] == "failed" and run["summary"] is None
        assert run["error"]["code"] == "RESULT_LIMIT_EXCEEDED"
        for suffix in (
            "issues",
            "exports/report-json",
            "exports/violations-csv",
            "exports/problematic-records-csv",
        ):
            response = connection.get(f"{API}/runs/{run_id}/{suffix}")
            assert (
                response.status_code == 409 and response.json()["error"]["code"] == "RUN_NOT_READY"
            )
        assert not list((tmp_path / "staging").iterdir())
        config = copy.deepcopy(RULES)
        config["check_duplicate_rows"] = False
        for rule in config["columns"]:
            rule.update(required=False, unique=False, expected_type="text", range=None)
        second = start(connection, dataset_id, config).json()["run_id"]
        assert wait_run(connection, second)["summary"]["total_issues"] == 0


def test_security_headers_and_bad_keys_cannot_change_state(client):
    path = f"{API}/datasets"
    attempts = [
        ({}, "REQUEST_GUARD_REQUIRED", 403),
        ({"X-Dataset-Check": "1"}, "REQUEST_INVALID", 422),
        ({**headers(), "Origin": "https://evil.example"}, "ORIGIN_NOT_ALLOWED", 403),
        ({**headers(), "Host": "evil.example"}, "ORIGIN_NOT_ALLOWED", 403),
    ]
    for request_headers, code, status in attempts:
        response = client.post(
            path, files={"file": ("input.csv", ACCEPTANCE)}, headers=request_headers
        )
        assert response.status_code == status
        error = response.json()["error"]
        assert error["code"] == code and error["request_id"]
    assert client.get(path).json()["total"] == 0
    assert client.options(
        path,
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Dataset-Check",
        },
    ).status_code in (400, 403)


def test_invalid_multipart_duplicate_parts_and_unsupported_extension(client):
    for parts in (
        [("file", ("input.csv", ACCEPTANCE)), ("file", ("again.csv", ACCEPTANCE))],
        [
            ("file", ("input.csv", ACCEPTANCE)),
            ("delimiter", (None, "comma")),
            ("delimiter", (None, "comma")),
        ],
        [("file", ("input.csv", ACCEPTANCE)), ("unexpected", (None, "x"))],
    ):
        response = client.post(f"{API}/datasets", files=parts, headers=headers())
        assert response.status_code == 422 and response.json()["error"]["code"] == "REQUEST_INVALID"
    invalid = client.post(
        f"{API}/datasets",
        content=b"not multipart",
        headers={**headers(), "Content-Type": "multipart/form-data; boundary=abc"},
    )
    assert invalid.status_code == 422
    wrong_extension = client.post(
        f"{API}/datasets", files={"file": ("input.xlsx", ACCEPTANCE)}, headers=headers()
    )
    assert wrong_extension.status_code == 415
    assert client.get(f"{API}/datasets").json()["total"] == 0
    assert not list(client.app.state.settings.data_dir.joinpath("staging").iterdir())


def test_body_limit_without_content_length_and_file_limit(tmp_path):
    with TestClient(
        create_app(settings_for(tmp_path, max_request_body_bytes=128, max_file_size_bytes=64))
    ) as connection:
        body = (
            b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="input.csv"\r\n\r\na,b\n'
            + b"x,y\n" * 40
            + b"\r\n--boundary--\r\n"
        )
        response = connection.post(
            f"{API}/datasets",
            content=iter([body[:100], body[100:]]),
            headers={**headers(), "Content-Type": "multipart/form-data; boundary=boundary"},
        )
        assert response.status_code == 413 and response.json()["error"]["code"] == "FILE_TOO_LARGE"
        assert connection.get(f"{API}/datasets").json()["total"] == 0
        assert not list((tmp_path / "staging").iterdir())


def test_list_does_not_touch_ttl_and_expiry_removes_source(client):
    dataset_id = upload(client).json()["dataset_id"]
    store = client.app.state.manager.store
    with store.connect() as db:
        expiry = time.time() + 30
        db.execute("UPDATE datasets SET expires=? WHERE id=?", (expiry, dataset_id))
    client.get(f"{API}/datasets")
    with store.connect() as db:
        assert (
            db.execute("SELECT expires FROM datasets WHERE id=?", (dataset_id,)).fetchone()[0]
            == expiry
        )
        db.execute("UPDATE datasets SET expires=? WHERE id=?", (time.time() - 1, dataset_id))
    assert client.get(f"{API}/datasets").json()["total"] == 0
    assert client.get(f"{API}/datasets/{dataset_id}").status_code == 404
    store.cleanup()
    assert not (store.root / "datasets" / dataset_id).exists()


def test_export_pin_blocks_deletion_and_restart_unpins(control):
    connection, dataset_id, run_id = control
    store = connection.app.state.manager.store
    store.pin_export(run_id, 1)
    try:
        assert connection.get(f"{API}/datasets/{dataset_id}").json()["retention_pinned"] is True
        assert (
            connection.delete(f"{API}/datasets/{dataset_id}", headers=headers()).status_code == 409
        )
        assert connection.delete(f"{API}/runs/{run_id}", headers=headers()).status_code == 409
    finally:
        store.pin_export(run_id, -1)
    assert connection.get(f"{API}/datasets/{dataset_id}").json()["retention_pinned"] is False
    assert connection.delete(f"{API}/runs/{run_id}", headers=headers()).status_code == 204


def test_accepted_import_error_is_replayed_without_publishing_partial_dataset(client):
    key = str(uuid.uuid4())
    payload = {"file": ("broken.csv", b'a,b\n"unfinished,y\n', "text/csv")}
    first = client.post(
        f"{API}/datasets", files=payload, data={"delimiter": "comma"}, headers=headers(key)
    )
    assert first.status_code == 400 and first.json()["error"]["code"] == "CSV_PARSE_ERROR"
    second = client.post(
        f"{API}/datasets", files=payload, data={"delimiter": "comma"}, headers=headers(key)
    )
    assert second.status_code == first.status_code and second.json() == first.json()
    assert second.headers["idempotency-replayed"] == "true"
    assert client.get(f"{API}/datasets").json()["total"] == 0
    assert not list(client.app.state.settings.data_dir.joinpath("staging").iterdir())
    assert upload(client).status_code == 201


def test_concurrent_same_key_and_busy_processor_do_not_create_duplicate_operations(
    client, monkeypatch
):
    service = client.app.state.manager
    original = service.execute

    def delayed(payload, timeout, run_id=None):
        return original(payload | {"test_delay": 1}, timeout, run_id)

    monkeypatch.setattr(service, "execute", delayed)
    key, rejected_key = str(uuid.uuid4()), str(uuid.uuid4())
    outcome = []

    def submit():
        outcome.append(
            client.post(
                f"{API}/datasets",
                files={"file": ("acceptance.csv", ACCEPTANCE)},
                headers=headers(key),
            )
        )

    thread = threading.Thread(target=submit)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while (
            service.store.request(f"POST:{API}/datasets", key) is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        in_progress = client.post(
            f"{API}/datasets", files={"file": ("acceptance.csv", ACCEPTANCE)}, headers=headers(key)
        )
        assert (
            in_progress.status_code == 409
            and in_progress.json()["error"]["code"] == "IDEMPOTENCY_IN_PROGRESS"
        )
        assert in_progress.headers["retry-after"] == "1"
        blocked = client.post(
            f"{API}/datasets",
            files={"file": ("acceptance.csv", ACCEPTANCE)},
            headers=headers(rejected_key),
        )
        assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "PROCESSOR_BUSY"
    finally:
        thread.join(timeout=15)
    assert not thread.is_alive() and outcome[0].status_code == 201
    assert client.get(f"{API}/datasets").json()["total"] == 1
    monkeypatch.setattr(service, "execute", original)
    assert upload(client, key=rejected_key).status_code == 201


def test_queued_run_recovers_as_failed_and_replay_keeps_same_id(tmp_path, monkeypatch):
    config = settings_for(tmp_path)
    key = str(uuid.uuid4())
    with TestClient(create_app(config)) as connection:
        dataset_id = upload(connection).json()["dataset_id"]
        monkeypatch.setattr(connection.app.state.manager, "start_run", lambda *args: None)
        receipt = start(connection, dataset_id, key=key).json()
        assert connection.get(receipt["status_url"]).json()["status"] == "queued"
    with TestClient(create_app(config)) as connection:
        run = connection.get(receipt["status_url"]).json()
        assert run["status"] == "failed" and run["error"]["code"] == "PROCESS_RESTARTED"
        assert run["summary"] is None and run["started_at"] is None and run["duration_ms"] is None
        assert run["finished_at"] is not None
        assert run["retention_pinned"] is False
        assert start(connection, dataset_id, key=key).json() == receipt


def test_storage_quota_failure_preserves_previous_successful_report(control):
    connection, _, previous_run_id = control
    previous_report = connection.get(f"{API}/runs/{previous_run_id}/exports/report-json").content
    dataset_id = upload(
        connection, b"n\n" + (b"x" * 100 + b"\n") * 1000, parameters={"delimiter": "comma"}
    ).json()["dataset_id"]
    config = {
        "schema_version": "1.0",
        "decimal_separator": ".",
        "check_duplicate_rows": False,
        "columns": [
            {
                "column_id": "c1",
                "required": False,
                "unique": False,
                "expected_type": "integer",
                "range": None,
            }
        ],
    }
    service = connection.app.state.manager
    original_limit = service.settings.limits["max_storage_bytes"]
    service.settings.limits["max_storage_bytes"] = (
        service.store.used_bytes() + service.settings.limits["storage_reserve_bytes"] + 131072
    )
    try:
        run_id = start(connection, dataset_id, config).json()["run_id"]
        run = wait_run(connection, run_id)
        assert run["status"] == "failed" and run["summary"] is None
        assert run["error"]["code"] == "STORAGE_QUOTA_EXCEEDED"
        assert (
            connection.get(f"{API}/runs/{previous_run_id}/exports/report-json").content
            == previous_report
        )
        assert not list(service.store.root.joinpath("staging").iterdir())
        assert connection.delete(f"{API}/runs/{run_id}", headers=headers()).status_code == 204
    finally:
        service.settings.limits["max_storage_bytes"] = original_limit
    run_id = start(connection, dataset_id, config).json()["run_id"]
    assert wait_run(connection, run_id)["summary"]["total_issues"] == 1000


def test_cleanup_rechecks_expiry_after_concurrent_user_activity(client, monkeypatch):
    dataset_id = upload(client).json()["dataset_id"]
    store = client.app.state.manager.store
    with store.connect() as db:
        db.execute("UPDATE datasets SET expires=? WHERE id=?", (time.time() - 1, dataset_id))
    original_delete = store.delete_dataset

    def touched_before_delete(resource_id, expired=False):
        # A request refreshed the selected dataset after the cleaner's SELECT.
        with store.connect() as db:
            db.execute(
                "UPDATE datasets SET expires=? WHERE id=?", (time.time() + 3600, resource_id)
            )
        return original_delete(resource_id, expired=expired)

    monkeypatch.setattr(store, "delete_dataset", touched_before_delete)
    store.cleanup()
    assert client.get(f"{API}/datasets/{dataset_id}").status_code == 200


def test_start_rechecks_dataset_existence_before_publishing_run(client, monkeypatch):
    dataset_id = upload(client).json()["dataset_id"]
    service = client.app.state.manager
    original_acquire = service.acquire

    def deletion_during_start():
        # The DELETE completed after the route loaded dataset metadata and
        # before it atomically published/pinned the new run.
        service.store.delete_dataset(dataset_id)
        return original_acquire()

    monkeypatch.setattr(service, "acquire", deletion_during_start)
    response = client.post(f"{API}/datasets/{dataset_id}/runs", json=RULES, headers=headers())
    assert response.status_code == 404
    with service.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    assert not service.gate.locked()


def test_multipart_receive_timeout_cleans_partial_upload_and_releases_processor(tmp_path):
    async def scenario():
        application = create_app(settings_for(tmp_path, upload_timeout_seconds=1))
        prefix = b'--slow\r\nContent-Disposition: form-data; name="file"; filename="input.csv"\r\n\r\na,b\nx,'

        async def slow_upload():
            yield prefix
            await asyncio.sleep(1.2)
            yield b"y\n\r\n--slow--\r\n"

        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://testserver"
            ) as connection:
                response = await connection.post(
                    f"{API}/datasets",
                    content=slow_upload(),
                    headers={**headers(), "Content-Type": "multipart/form-data; boundary=slow"},
                )
                assert response.status_code == 408
                assert response.json()["error"]["code"] == "UPLOAD_TIMEOUT"
                assert not list((tmp_path / "staging").iterdir())
                assert not application.state.manager.gate.locked()
                valid = await connection.post(
                    f"{API}/datasets",
                    files={"file": ("acceptance.csv", ACCEPTANCE)},
                    headers=headers(),
                )
                assert valid.status_code == 201, valid.text

    asyncio.run(scenario())


def test_restart_during_export_clears_pins_and_restores_expired_dataset(tmp_path):
    config = settings_for(tmp_path)
    with TestClient(create_app(config)) as connection:
        dataset_id = upload(connection).json()["dataset_id"]
        run_id = start(connection, dataset_id).json()["run_id"]
        assert wait_run(connection, run_id)["status"] == "succeeded"
        report = connection.get(f"{API}/runs/{run_id}/exports/report-json").content
        store = connection.app.state.manager.store
        store.pin_export(run_id, 1)
        with store.connect() as db:
            db.execute("UPDATE datasets SET expires=? WHERE id=?", (time.time() - 1, dataset_id))
        # Persisted pin deliberately remains: same state as an interrupted
        # HTTP process whose export generator could not run its finally block.
    with TestClient(create_app(config)) as connection:
        response = connection.get(f"{API}/datasets/{dataset_id}")
        assert response.status_code == 200
        dataset = response.json()
        assert dataset["retention_pinned"] is False and dataset["expires_at"] is not None
        assert connection.get(f"{API}/runs/{run_id}/exports/report-json").content == report
        with connection.app.state.manager.store.connect() as db:
            assert (
                db.execute("SELECT export_pins FROM runs WHERE id=?", (run_id,)).fetchone()[0] == 0
            )


def test_run_initialization_failure_does_not_leave_queued_pinned_resource(client, monkeypatch):
    dataset_id = upload(client).json()["dataset_id"]
    key = str(uuid.uuid4())
    service = client.app.state.manager

    def cannot_initialize(*args):
        raise AppError("TEMP_STORAGE_UNAVAILABLE", "Injected staging initialization failure", 507)

    monkeypatch.setattr(service, "start_run", cannot_initialize)
    response = client.post(f"{API}/datasets/{dataset_id}/runs", json=RULES, headers=headers(key))
    assert response.status_code in (202, 507)
    request = service.store.request(f"POST:{API}/datasets/{dataset_id}/runs", key)
    assert request is not None and request["resource_id"]
    run = client.get(f"{API}/runs/{request['resource_id']}").json()
    assert run["status"] == "failed"
    assert run["error"]["code"] == "TEMP_STORAGE_UNAVAILABLE"
    assert run["retention_pinned"] is False
    assert not service.gate.locked()


@pytest.mark.parametrize("failure_point", ["rename", "publish_dataset"])
def test_import_publication_io_failure_is_replayed_and_cleans_unpublished_files(
    client, monkeypatch, failure_point
):
    service = client.app.state.manager
    store = service.store
    key = str(uuid.uuid4())
    original_rename = Path.rename

    with monkeypatch.context() as patch:
        if failure_point == "rename":

            def cannot_publish_directory(path, target):
                target_path = Path(target)
                if path.parent.name == "staging" and target_path.parent == store.root / "datasets":
                    raise OSError("Injected dataset directory publication failure")
                return original_rename(path, target)

            patch.setattr(Path, "rename", cannot_publish_directory)
        else:

            def cannot_publish_metadata(*args):
                raise sqlite3.OperationalError("Injected catalogue publication failure")

            patch.setattr(store, "publish_dataset", cannot_publish_metadata)

        request_files = {"file": ("acceptance.csv", ACCEPTANCE, "text/csv")}
        first = client.post(f"{API}/datasets", files=request_files, headers=headers(key))
        assert first.status_code == 507
        assert first.json()["error"]["code"] == "TEMP_STORAGE_UNAVAILABLE"
        second = client.post(f"{API}/datasets", files=request_files, headers=headers(key))
        assert second.status_code == 507 and second.json() == first.json()
        assert second.headers["idempotency-replayed"] == "true"
        assert client.get(f"{API}/datasets").json()["total"] == 0
        assert not list((store.root / "staging").iterdir())
        assert not list((store.root / "datasets").iterdir())
        assert not service.gate.locked()

    assert upload(client).status_code == 201
