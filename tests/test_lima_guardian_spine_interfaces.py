from __future__ import annotations

import importlib
from pathlib import Path

from lima_guardian.spine_interfaces import DashboardAdapter, SpineEventBus, SpineStore
from lima_guardian.spine_models import (
    SpineDashboardSnapshot,
    SpineEntityType,
    SpineEventEnvelope,
    SpineEventType,
    SpineProducer,
    SpineProject,
    SpineRelation,
    SpineTask,
)


def test_event_envelope_serializes_with_metadata_and_redacted_flag():
    e = SpineEventEnvelope(
        event_id="evt-1",
        event_type="task.created",
        category=SpineEventType.TASK,
        room_id="room-1",
        source_kind="message",
        source_ref="msg-1",
        payload={"tool_args": {"api_key": "[REDACTED]"}},
        metadata={"trace": "abc"},
        redacted=True,
    )
    d = e.to_dict()
    e2 = SpineEventEnvelope.from_dict(d)
    assert e2.event_id == "evt-1"
    assert e2.category == SpineEventType.TASK
    assert e2.metadata["trace"] == "abc"
    assert e2.redacted is True


def test_task_and_project_round_trip_dict():
    task = SpineTask(
        task_id="t-1",
        title="Do the thing",
        room_id="room-1",
        tags=["a", "b"],
        metadata={"x": 1},
    )
    task2 = SpineTask.from_dict(task.to_dict())
    assert task2 == task

    project = SpineProject(project_id="p-1", display_name="Project", tags=["x"], metadata={"k": "v"})
    project2 = SpineProject.from_dict(project.to_dict())
    assert project2 == project


def test_relation_round_trip_dict():
    rel = SpineRelation(
        relation_id="r-1",
        from_entity_type=SpineEntityType.TASK,
        from_entity_id="t-1",
        to_entity_type=SpineEntityType.TASK,
        to_entity_id="t-2",
        relation_type="dependency",
        metadata={"w": 1},
    )
    rel2 = SpineRelation.from_dict(rel.to_dict())
    assert rel2 == rel


def test_dashboard_snapshot_round_trip_dict():
    snap = SpineDashboardSnapshot(
        room_id="room-1",
        captured_at="2026-01-01T00:00:00Z",
        status_counts={"open": 1},
        task_count=1,
        tasks=[SpineTask(task_id="t-1", title="A")],
        projects=[SpineProject(project_id="p-1", display_name="P")],
        recent_events=[SpineEventEnvelope(event_id="e1", event_type="x")],
        metadata={"m": True},
    )
    snap2 = SpineDashboardSnapshot.from_dict(snap.to_dict())
    assert snap2.room_id == "room-1"
    assert snap2.status_counts["open"] == 1
    assert snap2.tasks[0].task_id == "t-1"
    assert snap2.projects[0].project_id == "p-1"


def test_interfaces_can_be_implemented_in_memory():
    class FakeStore:
        def __init__(self) -> None:
            self._tasks: dict[str, SpineTask] = {}
            self._events: list[SpineEventEnvelope] = []

        def init_schema(self) -> None:
            return None

        def get_task(self, task_id: str):
            return self._tasks.get(task_id)

        def get_event(self, event_id: str):
            for event in self._events:
                if event.event_id == event_id:
                    return event
            return None

        def list_tasks(self, *, room_id=None, project_id=None, status=None, limit=100):
            _ = (room_id, project_id, status)
            return list(self._tasks.values())[:limit]

        def upsert_task(self, task: SpineTask):
            self._tasks[task.task_id] = task
            return task

        def get_project(self, project_id: str):
            return None

        def list_projects(self, *, room_id=None, limit=100):
            _ = (room_id, limit)
            return []

        def upsert_project(self, project: SpineProject):
            return project

        def append_event(self, event: SpineEventEnvelope):
            self._events.append(event)
            return event

        def list_events(self, *, room_id=None, task_id=None, project_id=None, subsystem=None, limit=100):
            _ = (room_id, task_id, project_id, subsystem)
            return self._events[:limit]

        def record_relation(self, relation: SpineRelation):
            return relation

        def list_relations(self, *, from_entity_id=None, to_entity_id=None, relation_type=None, limit=200):
            _ = (from_entity_id, to_entity_id, relation_type, limit)
            return []

        def register_producer(self, producer: SpineProducer):
            return producer

        def list_producers(self):
            return []

        def get_dashboard_snapshot(self, *, room_id=None, limit=20):
            _ = (room_id, limit)
            return SpineDashboardSnapshot(room_id=room_id, captured_at="2026-01-01T00:00:00Z")

    class FakeBus:
        def __init__(self) -> None:
            self._producers: list[SpineProducer] = []

        def register_producer(self, producer: SpineProducer):
            self._producers.append(producer)
            return producer

        def list_producers(self):
            return list(self._producers)

        def ingest(self, event: SpineEventEnvelope):
            return {"event_id": event.event_id, "event_type": event.event_type}

    store: SpineStore = FakeStore()
    bus: SpineEventBus = FakeBus()

    store.upsert_task(SpineTask(task_id="t-1", title="X"))
    assert store.get_task("t-1") is not None
    assert bus.ingest(SpineEventEnvelope(event_id="e-1", event_type="task.created"))["event_type"] == "task.created"


def test_no_disallowed_imports_in_interfaces_or_models():
    mods = [
        importlib.import_module("lima_guardian.spine_models"),
        importlib.import_module("lima_guardian.spine_interfaces"),
    ]
    for mod in mods:
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "from app" not in src
        assert "import app" not in src
        assert "fastapi" not in src.lower()
        assert "sqlmodel" not in src.lower()
