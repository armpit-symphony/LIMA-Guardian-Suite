from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path

from tools.spine_serializer_fixture_compare import build_report, main, write_report


def _create_sample_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE guardian_spine_tasks (
              task_id TEXT PRIMARY KEY,
              room_id TEXT NOT NULL,
              title TEXT NOT NULL,
              summary TEXT,
              project_id TEXT,
              type TEXT NOT NULL,
              priority TEXT NOT NULL,
              status TEXT NOT NULL,
              owner_kind TEXT NOT NULL,
              owner_id TEXT,
              source_kind TEXT NOT NULL,
              source_ref TEXT NOT NULL,
              created_by_guardian TEXT NOT NULL,
              created_by_subsystem TEXT,
              updated_by_subsystem TEXT,
              approval_required INTEGER NOT NULL DEFAULT 0,
              approval_state TEXT NOT NULL DEFAULT 'not_required',
              confidence REAL NOT NULL,
              parent_task_id TEXT,
              depends_on_json TEXT NOT NULL DEFAULT '[]',
              tags_json TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              last_progress_at TEXT NOT NULL,
              closed_at TEXT,
              source_excerpt TEXT,
              chat_task_id TEXT
            );
            CREATE TABLE guardian_spine_projects (
              project_id TEXT PRIMARY KEY,
              room_id TEXT,
              display_name TEXT NOT NULL,
              slug TEXT NOT NULL UNIQUE,
              summary TEXT,
              status TEXT,
              source_kind TEXT,
              source_ref TEXT,
              created_by_subsystem TEXT,
              updated_by_subsystem TEXT,
              tags_json TEXT,
              parent_project_id TEXT,
              created_at TEXT,
              updated_at TEXT NOT NULL,
              owner_kind TEXT DEFAULT 'unassigned',
              owner_id TEXT
            );
            CREATE TABLE guardian_spine_events (
              event_id TEXT PRIMARY KEY,
              event_type TEXT NOT NULL,
              occurred_at TEXT NOT NULL,
              room_id TEXT,
              subsystem TEXT,
              actor_kind TEXT NOT NULL,
              actor_id TEXT,
              source_kind TEXT NOT NULL,
              source_ref TEXT NOT NULL,
              correlation_id TEXT NOT NULL,
              task_id TEXT,
              project_id TEXT,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE guardian_spine_links (
              id TEXT PRIMARY KEY,
              task_id TEXT NOT NULL,
              related_task_id TEXT NOT NULL,
              link_type TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO guardian_spine_tasks VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "task-1",
                    "room-1",
                    "Open task",
                    "Needs work",
                    "project-1",
                    "feature",
                    "high",
                    "open",
                    "unassigned",
                    None,
                    "message",
                    "msg-1",
                    "guardian_spine",
                    "task_master",
                    "task_master",
                    1,
                    "required",
                    0.91,
                    None,
                    json.dumps(["task-2"]),
                    json.dumps(["alpha"]),
                    "2026-05-02T00:00:00+00:00",
                    "2026-05-02T00:00:00+00:00",
                    "2026-05-02T00:00:00+00:00",
                    None,
                    "contains token=abc",
                    "chat-1",
                ),
                (
                    "task-2",
                    "room-1",
                    "Blocked task",
                    "Blocked now",
                    "project-1",
                    "ops",
                    "normal",
                    "blocked",
                    "human",
                    "user-1",
                    "message",
                    "msg-2",
                    "guardian_spine",
                    "task_master",
                    "task_master",
                    0,
                    "not_required",
                    0.7,
                    None,
                    json.dumps([]),
                    json.dumps(["beta"]),
                    "2026-05-02T00:00:00+00:00",
                    "2026-05-02T00:00:00+00:00",
                    "2026-05-02T00:00:00+00:00",
                    None,
                    None,
                    "chat-2",
                ),
            ],
        )
        conn.execute(
            """
            INSERT INTO guardian_spine_projects VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "project-1",
                "room-1",
                "Project One",
                "project-one",
                "Project summary",
                "active",
                "system",
                "proj-src-1",
                "project_lifecycle",
                "project_lifecycle",
                json.dumps(["ops"]),
                None,
                "2026-05-02T00:00:00+00:00",
                "2026-05-02T00:00:00+00:00",
                "human",
                "user-1",
            ),
        )
        conn.executemany(
            """
            INSERT INTO guardian_spine_events VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "evt-1",
                    "approval.required",
                    "2026-05-02T00:00:00+00:00",
                    "room-1",
                    "approval",
                    "system",
                    None,
                    "approval",
                    "confirm-1",
                    "corr-1",
                    "task-1",
                    "project-1",
                    json.dumps({"tool_args": {"api_key": "secret-value"}, "safe": True}),
                ),
                (
                    "evt-2",
                    "handoff.created",
                    "2026-05-02T01:00:00+00:00",
                    "room-1",
                    "handoff",
                    "system",
                    None,
                    "task_master",
                    "handoff-1",
                    "corr-2",
                    "task-2",
                    "project-1",
                    json.dumps({"summary": "handoff"}),
                ),
            ],
        )
        conn.execute(
            """
            INSERT INTO guardian_spine_links VALUES
            (?, ?, ?, ?, ?)
            """,
            ("rel-1", "task-1", "task-2", "dependency", "2026-05-02T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def _fixture_dir() -> Path:
    return Path("/tmp/lima-guardian-suite/tests/fixtures/spine_serializer_expected")


def test_missing_db_fails_safely(tmp_path, capsys):
    output = tmp_path / "report.json"
    code = main(["--source-db", str(tmp_path / "missing.db"), "--fixture-dir", str(_fixture_dir()), "--output", str(output)])
    captured = capsys.readouterr()
    assert code == 2
    assert "Source DB not found" in captured.err
    assert not output.exists()


def test_temp_copy_is_used(tmp_path):
    source = tmp_path / "source.db"
    _create_sample_db(source)
    report = build_report(source, _fixture_dir())
    assert report["used_temp_copy"] is True
    assert report["temp_copy_path"] != report["source_db_path"]


def test_open_queue_fixture_comparison(tmp_path):
    source = tmp_path / "source.db"
    _create_sample_db(source)
    report = build_report(source, _fixture_dir())
    assert report["comparisons"]["open_queue"]["match"] is True


def test_task_detail_fixture_comparison(tmp_path):
    source = tmp_path / "source.db"
    _create_sample_db(source)
    report = build_report(source, _fixture_dir())
    assert report["comparisons"]["task_detail"]["match"] is True


def test_volatile_fields_normalized(tmp_path):
    source = tmp_path / "source.db"
    _create_sample_db(source)
    report = build_report(source, _fixture_dir())
    preview = report["comparisons"]["open_queue"]["normalized_preview"]
    assert preview["tasks"][0]["task_id"] == "<id>"
    assert preview["tasks"][0]["created_at"] == "<timestamp>"
    assert preview["tasks"][0]["source_ref"] == "<ref>"


def test_secret_like_values_redacted(tmp_path):
    source = tmp_path / "source.db"
    output = tmp_path / "report.json"
    _create_sample_db(source)
    write_report(source, _fixture_dir(), output)
    report_text = output.read_text(encoding="utf-8")
    assert "secret-value" not in report_text
    data = json.loads(report_text)
    event_preview = data["comparisons"]["task_detail"]["normalized_preview"]["events"][0]
    assert event_preview["payload"]["tool_args"]["api_key"] == "[REDACTED]"


def test_json_report_generated(tmp_path):
    source = tmp_path / "source.db"
    output = tmp_path / "report.json"
    _create_sample_db(source)
    report = write_report(source, _fixture_dir(), output)
    data = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["pass"] is True
    assert data["summary"]["pass"] is True


def test_no_disallowed_imports():
    mod = importlib.import_module("tools.spine_serializer_fixture_compare")
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "from app" not in src
    assert "import app" not in src
    assert "from sparkbot" not in src.lower()
    assert "import sparkbot\n" not in src.lower()
    assert "import sparkbot " not in src.lower()
    assert "fastapi" not in src.lower()
    assert "sqlmodel" not in src.lower()
