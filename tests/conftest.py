from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def giant_sql(tmp_path: Path) -> Path:
    path = tmp_path / "giant.sql"
    statements = []
    for idx in range(1000):
        statements.append(
            "CREATE TABLE batch_{idx} (id INTEGER PRIMARY KEY, value TEXT);\n"
            "INSERT INTO batch_{idx} (id, value) VALUES ({idx}, 'row {idx}');".format(idx=idx)
        )
    path.write_text("\n".join(statements) + "\n", encoding="utf-8")
    return path
