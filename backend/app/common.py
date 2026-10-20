from __future__ import annotations

import json
import time
from datetime import UTC, datetime


class AppError(Exception):
    def __init__(self, code, message, status=400, details=None, headers=None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.details = details if details is not None else []
        self.headers = headers or {}


def iso(value=None):
    return (
        datetime.fromtimestamp(time.time() if value is None else value, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
