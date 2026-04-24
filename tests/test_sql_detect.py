from __future__ import annotations

from pathlib import Path

from graphify.detect import FileType, SQL_EXTENSIONS, classify_file, detect


SQL_FIXTURES = Path(__file__).parent / "fixtures" / "sql"


def test_classify_sql_file():
    assert classify_file(Path("schema.sql")) == FileType.SQL


def test_sql_extension_constant():
    assert ".sql" in SQL_EXTENSIONS


def test_detect_includes_sql_files():
    result = detect(SQL_FIXTURES)
    sql_files = result["files"]["sql"]
    assert any(path.endswith("schema.sql") for path in sql_files)
    assert any(path.endswith("views.sql") for path in sql_files)


def test_graphifyignore_excludes_sql_files(tmp_path):
    (tmp_path / ".graphifyignore").write_text("queries.sql\n", encoding="utf-8")
    (tmp_path / "schema.sql").write_text("CREATE TABLE users (id INT);", encoding="utf-8")
    (tmp_path / "queries.sql").write_text("SELECT * FROM users;", encoding="utf-8")

    result = detect(tmp_path)

    assert any(path.endswith("schema.sql") for path in result["files"]["sql"])
    assert not any(path.endswith("queries.sql") for path in result["files"]["sql"])


def test_detect_skips_graphify_out_sql(tmp_path):
    (tmp_path / "schema.sql").write_text("CREATE TABLE users (id INT);", encoding="utf-8")
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "generated.sql").write_text("CREATE TABLE ignored (id INT);", encoding="utf-8")

    result = detect(tmp_path)

    assert any(path.endswith("schema.sql") for path in result["files"]["sql"])
    assert not any(path.endswith("generated.sql") for path in result["files"]["sql"])
