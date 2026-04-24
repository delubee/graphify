from __future__ import annotations

import sys
from pathlib import Path

import pytest


def test_parse_sql_options_valid():
    from graphify.__main__ import _parse_sql_options

    options = _parse_sql_options([
        "--sql-dialect", "postgres",
        "--sql-object-level", "column",
        "--sql-lineage",
        "--sql-embedded",
    ])

    assert options == {
        "sql_dialect": "postgres",
        "sql_object_level": "column",
        "sql_lineage": True,
        "sql_embedded": True,
    }


def test_parse_sql_options_invalid_dialect():
    from graphify.__main__ import _parse_sql_options

    with pytest.raises(ValueError, match="invalid --sql-dialect value 'bogus'"):
        _parse_sql_options(["--sql-dialect", "bogus"])


def test_update_command_threads_sql_options(tmp_path, monkeypatch):
    from graphify import __main__

    captured = {}

    def fake_rebuild(path: Path, **kwargs):
        captured["path"] = path
        captured["kwargs"] = kwargs
        return True

    monkeypatch.setattr("graphify.watch._rebuild_code", fake_rebuild)
    monkeypatch.setattr(sys, "argv", [
        "graphify",
        "update",
        str(tmp_path),
        "--sql-dialect", "sqlite",
        "--sql-object-level", "column",
        "--sql-lineage",
        "--sql-embedded",
    ])

    __main__.main()

    assert captured["path"] == tmp_path
    assert captured["kwargs"]["sql_dialect"] == "sqlite"
    assert captured["kwargs"]["sql_object_level"] == "column"
    assert captured["kwargs"]["sql_lineage"] is True
    assert captured["kwargs"]["sql_embedded"] is True


def test_watch_command_threads_sql_options(tmp_path, monkeypatch):
    from graphify import __main__

    captured = {}

    def fake_watch(path: Path, **kwargs):
        captured["path"] = path
        captured["kwargs"] = kwargs

    monkeypatch.setattr("graphify.watch.watch", fake_watch)
    monkeypatch.setattr(sys, "argv", [
        "graphify",
        "watch",
        str(tmp_path),
        "--sql-dialect", "mysql",
        "--sql-object-level", "file",
    ])

    __main__.main()

    assert captured["path"] == tmp_path
    assert captured["kwargs"]["sql_dialect"] == "mysql"
    assert captured["kwargs"]["sql_object_level"] == "file"
    assert captured["kwargs"]["sql_lineage"] is False
    assert captured["kwargs"]["sql_embedded"] is False
