"""Safe errors that can be passed across a worker-process boundary."""

from typing import Any


class DomainError(Exception):
    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(code, message, details if details is not None else {})
        self.code = code
        self.message = message
        self.details = details if details is not None else {}

    def __str__(self) -> str:
        return self.message
