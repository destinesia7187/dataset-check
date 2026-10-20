"""Small HTTP client shared by reproducible command-line demonstrations."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import httpx


class DatasetCheckClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000") -> None:
        self.http = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v1/",
            timeout=httpx.Timeout(180, connect=5),
            headers={"X-Dataset-Check": "1"},
            trust_env=False,
        )
        self.last_import_seconds: float | None = None

    def __enter__(self) -> DatasetCheckClient:
        self.http.__enter__()
        return self

    def __exit__(self, *args: object) -> None:
        self.http.__exit__(*args)

    def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        response = self.http.request(method, path, **kwargs)
        if response.is_error:
            try:
                detail = json.dumps(response.json(), ensure_ascii=False)
            except ValueError:
                detail = response.text[:1000]
            raise RuntimeError(
                f"{method} {path}: HTTP {response.status_code}: {detail}"
            )
        return response

    def upload(self, path: Path, key: str | None = None) -> tuple[dict, float]:
        with path.open("rb") as stream:
            started = time.perf_counter()
            response = self.request(
                "POST",
                "datasets",
                files={"file": (path.name, stream, "text/csv")},
                data={"encoding": "utf-8", "delimiter": "comma"},
                headers={"Idempotency-Key": key or str(uuid.uuid4())},
            )
            elapsed = time.perf_counter() - started
            self.last_import_seconds = None
            for part in response.headers.get("Server-Timing", "").split(","):
                parameters = [parameter.strip() for parameter in part.split(";")]
                if parameters[0] == "import":
                    for parameter in parameters[1:]:
                        if parameter.startswith("dur="):
                            self.last_import_seconds = float(parameter[4:]) / 1000
            return response.json(), elapsed

    def start(self, dataset_id: str, rules: dict, key: str | None = None) -> dict:
        return self.request(
            "POST",
            f"datasets/{dataset_id}/runs",
            json=rules,
            headers={"Idempotency-Key": key or str(uuid.uuid4())},
        ).json()

    def wait(self, run_id: str, timeout: float = 150) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = self.request("GET", f"runs/{run_id}").json()
            if run["status"] in {"succeeded", "failed"}:
                return run
            time.sleep(0.2)
        raise TimeoutError(f"Run {run_id} did not finish within {timeout} seconds")

    def delete_dataset(self, dataset_id: str) -> None:
        self.request("DELETE", f"datasets/{dataset_id}")
