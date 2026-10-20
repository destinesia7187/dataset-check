from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALGORITHM_VERSION = "1.0.0"
DEFAULT_LIMITS = {
    "max_file_size_bytes": 20 * 1024 * 1024,
    "max_request_body_bytes": 20 * 1024 * 1024 + 65536,
    "max_rows": 100000,
    "max_columns": 100,
    "max_cells": 2000000,
    "max_cell_length_chars": 65536,
    "max_header_length_chars": 128,
    "max_filename_length_chars": 255,
    "max_multipart_file_parts": 1,
    "max_multipart_text_parts": 2,
    "max_multipart_text_length_chars": 64,
    "max_multipart_part_header_bytes": 8192,
    "max_datasets": 3,
    "max_runs_per_dataset": 3,
    "max_numeric_digits": 100,
    "default_page_size": 50,
    "max_page_size": 100,
    "dataset_idle_ttl_seconds": 3600,
    "cleanup_interval_seconds": 300,
    "idempotency_retention_after_completion_seconds": 86400,
    "max_issues_per_run": 100000,
    "import_timeout_seconds": 120,
    "run_timeout_seconds": 120,
    "upload_timeout_seconds": 60,
    "max_storage_bytes": 1024**3,
    "storage_reserve_bytes": 8 * 1024**2,
    "metadata_completion_reservation_bytes": 65536,
    "max_terminal_error_bytes": 16384,
    "cleanup_grace_seconds": 5,
}


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")
    frontend_dist: Path = field(default_factory=lambda: PROJECT_ROOT / "frontend" / "dist")
    limits: dict = field(default_factory=dict)
    allowed_hosts: tuple = ("localhost", "127.0.0.1", "[::1]")
    allowed_origins: tuple = (
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    def __post_init__(self):
        self.data_dir = Path(self.data_dir).resolve()
        self.frontend_dist = Path(self.frontend_dist).resolve()
        self.limits = DEFAULT_LIMITS | self.limits
        if any(not isinstance(v, int) or v <= 0 for v in self.limits.values()):
            raise ValueError("All limits must be positive integers")
        if self.limits["storage_reserve_bytes"] >= self.limits["max_storage_bytes"]:
            raise ValueError("The reserve must be smaller than the total quota")

    @classmethod
    def from_env(cls):
        limits = {
            key: int(os.environ[key.upper()]) for key in DEFAULT_LIMITS if key.upper() in os.environ
        }
        extra = {}
        for attr, env in (
            ("allowed_hosts", "ALLOWED_HOSTS"),
            ("allowed_origins", "ALLOWED_ORIGINS"),
        ):
            if env in os.environ:
                extra[attr] = tuple(x.strip() for x in os.environ[env].split(",") if x.strip())
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data")),
            frontend_dist=Path(os.getenv("FRONTEND_DIST", PROJECT_ROOT / "frontend" / "dist")),
            limits=limits,
            **extra,
        )

    def capabilities(self):
        return {
            "config_schema_version": "1.0",
            "report_schema_version": "1.1",
            "algorithm_version": ALGORITHM_VERSION,
            "supported_encodings": ["utf-8", "windows-1251"],
            "supported_delimiters": ["auto", "comma", "semicolon", "tab"],
            "supported_types": ["text", "integer", "decimal", "date"],
            "defaults": {"encoding": "utf-8", "delimiter": "auto", "decimal_separator": "."},
            "limits": self.limits,
        }
