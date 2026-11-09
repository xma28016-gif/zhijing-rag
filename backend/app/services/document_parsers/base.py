"""Replaceable parser protocol and explicit parser failures."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.schemas.knowledge import ParseResult


class DocumentParseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


class DocumentParser(Protocol):
    def parse(self, path: Path, *, filename: str | None = None) -> ParseResult: ...
