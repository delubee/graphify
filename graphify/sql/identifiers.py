from __future__ import annotations

import re

from graphify.extract import _make_id


def _make_sql_id(kind: str, *parts: str) -> str:
    return _make_id(kind, *parts)


def normalize_identifier(raw: str, quoted: bool = False) -> str:
    text = raw.strip()
    if text and text[0] in ('"', "'", "`", "[") and text[-1] in ('"', "'", "`", "]"):
        text = text[1:-1]
        quoted = True
    return text if quoted else text.lower()


def resolve_default_schema(text: str) -> str:
    search_path = re.search(r"SET\s+search_path\s*=\s*([A-Za-z_][\w$]*)", text, re.IGNORECASE)
    if search_path:
        return search_path.group(1).lower()
    create_schema = re.search(r"CREATE\s+SCHEMA\s+([A-Za-z_][\w$]*)", text, re.IGNORECASE)
    if create_schema:
        return create_schema.group(1).lower()
    qualified = re.search(
        r"\b(?:CREATE\s+(?:TABLE|VIEW|MATERIALIZED\s+VIEW)|INSERT\s+INTO|UPDATE|DELETE\s+FROM|FROM|JOIN)\s+([A-Za-z_][\w$]*)\.([A-Za-z_][\w$]*)",
        text,
        re.IGNORECASE,
    )
    if qualified:
        return qualified.group(1).lower()
    return "public"


def qualify(schema_name: str, object_name: str) -> str:
    return f"{schema_name}.{object_name}"


def qualify_column(schema_name: str, object_name: str, column_name: str) -> str:
    return f"{schema_name}.{object_name}.{column_name}"
