from __future__ import annotations

from typing import TypedDict


class SqlError(TypedDict):
    path: str
    line: int | None
    message: str


class SqlExtractionResult(TypedDict):
    nodes: list[dict]
    edges: list[dict]
    errors: list[SqlError]
