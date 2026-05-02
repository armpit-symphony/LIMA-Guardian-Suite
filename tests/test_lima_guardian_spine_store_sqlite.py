from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

from lima_guardian.spine_events import approval_event, build_event, task_event
from lima_guardian.spine_interfaces import SpineStore
from lima_guardian.spine_models import SpineEntityType, SpineEventType, SpineProducer, SpineProject, SpineRelation, SpineTask
from lima_guardian.spine_store_sqlite import CURRENT_SCHEMA_VERSION, SQLiteSpineStore


def make_store(tmp_path):
    db_path = tmp_path / "spine-test.db"
    store = SQLiteSpineStore(db_path)
    return store, db_path


def test_store_initializes_schema_and_schema_version(tmp_path):
    store, db_path = make_store(tmp_path)
    try:
        assert isinstance(store, SpineStore)
        assert db_path.exists()
        conn = sqlite3.connect(str(db_path))
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            assert "schema_version" in tables
            assert "spine_events" in tables
            assert "spine_tasks" in tables
            assert "spine_projects" in tables
            assert "spine_relations" in tables
            assert "spine_producers" in tables
            version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
            assert version == CURRENT_SCHEMA_VERSION
        finally:
            conn.close()
    finally:
        store.close()


def test_append_get_and_list_events_by_entity(tmp_path):
    store, _ = make_store(tmp_path)
    try:
        event1 = task_event(
            event_type="task.created",
            source_kind="test",
            source_ref="src-1",
            room_id="room-1",
            task_id="task-1",
            project_id="project-1",
            payload={"step": 1},
            metadata={"trace": "abc"},
        )
        event2 = approval_event(
            event_type="approval.required",
            source_kind="test",
            source_ref="src-2",
            room_id="room-1",
            task_id="task-1",
            payload={"decision": "review"},
        )
        store.append_event(event1)
        store.append_event(event2)

        loaded = store.get_event(event1.event_id)
        assert loaded is not None
        assert loaded.metadata["trace"] == "abc"

        task_events = store.list_events(task_id="task-1")
        assert len(task_events) == 2
        assert {event.event_type for event in task_events} == {"task.created", "approval.required"}

        project_only = store.list_events(project_id="project-1")
        assert len(project_only) == 1
        assert project_only[0].event_id == event1.event_id
    finally:
        store.close()


def test_task_create_update_and_list(tmp_path):
    store, _ = make_store(tmp_path)
    try:
        created = store.upsert_task(
            SpineTask(
                task_id="task-1",
                title="Initial",
                room_id="room-1",
                project_id="project-1",
                approval_required=True,
                approval_state="pending",
                tags=["ops"],
                depends_on=["task-0"],
                metadata={"note": "first"},
            )
        )
        updated = store.upsert_task(
            SpineTask.from_dict(
                {
                    **created.to_dict(),
                    "title": "Renamed",
                    "status": "in_progress",
                    "owner_kind": "user",
                    "owner_id": "u-1",
                    "metadata": {"note": "updated"},
                }
            )
        )

        fetched = store.get_task("task-1")
        assert fetched is not None
        assert fetched.title == "Renamed"
        assert fetched.status == "in_progress"
        assert fetched.owner_id == "u-1"
        assert fetched.created_at == created.created_at
        assert fetched.metadata["note"] == "updated"

        tasks = store.list_tasks(room_id="room-1", project_id="project-1")
        assert len(tasks) == 1
        assert tasks[0].task_id == "task-1"
    finally:
        store.close()


def test_project_create_update_and_list(tmp_path):
    store, _ = make_store(tmp_path)
    try:
        created = store.upsert_project(
            SpineProject(
                project_id="project-1",
                display_name="Project One",
                room_id="room-1",
                tags=["guardian"],
                metadata={"phase": 1},
            )
        )
        updated = store.upsert_project(
            SpineProject.from_dict(
                {
                    **created.to_dict(),
                    "display_name": "Project Prime",
                    "status": "paused",
                    "metadata": {"phase": 2},
                }
            )
        )

        fetched = store.get_project("project-1")
        assert fetched is not None
        assert fetched.display_name == "Project Prime"
        assert fetched.status == "paused"
        assert fetched.created_at == created.created_at
        assert updated.metadata["phase"] == 2

        projects = store.list_projects(room_id="room-1")
        assert len(projects) == 1
        assert projects[0].project_id == "project-1"
    finally:
        store.close()


def test_relation_add_and_list(tmp_path):
    store, _ = make_store(tmp_path)
    try:
        relation = SpineRelation(
            relation_id="rel-1",
            from_entity_type=SpineEntityType.TASK,
            from_entity_id="task-1",
            to_entity_type=SpineEntityType.PROJECT,
            to_entity_id="project-1",
            relation_type="belongs_to",
            metadata={"source": "test"},
        )
        store.record_relation(relation)
        relations = store.list_relations(from_entity_id="task-1")
        assert len(relations) == 1
        assert relations[0].metadata["source"] == "test"
    finally:
        store.close()


def test_register_and_list_producers(tmp_path):
    store, _ = make_store(tmp_path)
    try:
        store.register_producer(
            SpineProducer(
                subsystem="memory",
                description="memory events",
                event_types=["memory.signal"],
                metadata={"owner": "core"},
            )
        )
        producers = store.list_producers()
        assert len(producers) == 1
        assert producers[0].subsystem == "memory"
        assert producers[0].event_types == ["memory.signal"]
        assert producers[0].metadata["owner"] == "core"
    finally:
        store.close()


def test_dashboard_snapshot_returns_expected_counts(tmp_path):
    store, _ = make_store(tmp_path)
    try:
        store.upsert_project(SpineProject(project_id="project-1", display_name="One", room_id="room-1"))
        store.upsert_task(
            SpineTask(
                task_id="task-1",
                title="Needs approval",
                room_id="room-1",
                approval_required=True,
                approval_state="pending",
            )
        )
        store.upsert_task(
            SpineTask(
                task_id="task-2",
                title="Assigned",
                room_id="room-1",
                project_id="project-1",
                owner_kind="user",
                owner_id="u-1",
                status="in_progress",
            )
        )
        store.append_event(
            build_event(
                category=SpineEventType.HANDOFF,
                event_type="handoff.started",
                source_kind="test",
                source_ref="src-3",
                room_id="room-1",
                project_id="project-1",
                payload={"kind": "handoff"},
                metadata={"scope": "test"},
            )
        )
        snapshot = store.get_dashboard_snapshot(room_id="room-1", limit=10)
        assert snapshot.task_count == 2
        assert snapshot.project_count == 1
        assert snapshot.event_count == 1
        assert snapshot.awaiting_approval_count == 1
        assert snapshot.handoff_count == 1
        assert snapshot.orphan_task_count == 1
        assert snapshot.unassigned_open_task_count == 1
        assert snapshot.status_counts["open"] == 1
        assert snapshot.status_counts["in_progress"] == 1
    finally:
        store.close()


def test_metadata_round_trip(tmp_path):
    store, _ = make_store(tmp_path)
    try:
        store.upsert_task(
            SpineTask(
                task_id="task-1",
                title="Meta",
                metadata={"nested": {"flag": True}, "items": [1, 2]},
            )
        )
        loaded = store.get_task("task-1")
        assert loaded is not None
        assert loaded.metadata["nested"]["flag"] is True
        assert loaded.metadata["items"] == [1, 2]
    finally:
        store.close()


def test_no_disallowed_imports_and_temp_db_only(tmp_path):
    mod = importlib.import_module("lima_guardian.spine_store_sqlite")
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "from app" not in src
    assert "import app" not in src
    assert "fastapi" not in src.lower()
    assert "sqlmodel" not in src.lower()

    store, db_path = make_store(tmp_path)
    try:
        assert str(db_path).startswith(str(tmp_path))
    finally:
        store.close()
