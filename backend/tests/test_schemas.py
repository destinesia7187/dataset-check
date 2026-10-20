"""The published OpenAPI and offline example must match the client contract."""

import json
from pathlib import Path

from app.main import create_app
from app.schemas import Report
from app.settings import Settings


def test_openapi_documents_inputs_responses_and_resolvable_report_schema(tmp_path):
    schema = create_app(Settings(data_dir=tmp_path)).openapi()
    paths = schema["paths"]
    upload = paths["/api/v1/datasets"]["post"]
    multipart = upload["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert multipart["required"] == ["file"]
    assert multipart["properties"]["file"]["format"] == "binary"
    assert {p["name"] for p in upload["parameters"]} >= {"X-Dataset-Check", "Idempotency-Key"}
    run = paths["/api/v1/datasets/{dataset_id}/runs"]["post"]
    assert run["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/Configuration"
    )
    assert "201" in upload["responses"] and "202" in run["responses"]
    assert "configuration_snapshot" in schema["components"]["schemas"]["Run"]["properties"]
    assert "problematic_records" in schema["components"]["schemas"]["Report"]["properties"]

    def walk(value):
        if isinstance(value, dict):
            if "$ref" in value:
                ref = value["$ref"]
                assert ref.startswith("#/components/schemas/")
                assert ref.rsplit("/", 1)[-1] in schema["components"]["schemas"], ref
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(schema)


def test_checked_in_report_is_valid_lossless_and_self_contained():
    path = Path(__file__).resolve().parents[2] / "examples/synthetic/report.example.json"
    raw = json.loads(path.read_text("utf-8"))
    report = Report.model_validate(raw)
    assert report.model_dump() == raw
    assert report.summary.total_issues == 13
    assert len(report.problematic_records) == 8
    assert report.problematic_records[7].values[2] == "  "
    assert sum(record.violation_count for record in report.problematic_records) == 13
