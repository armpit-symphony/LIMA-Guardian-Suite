"""Test-only Sparkbot route-shape parity checks over temp-copy data."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lima_guardian.spine_models import SpineEventEnvelope, SpineProject, SpineRelation, SpineTask
from tools.spine_readonly_adapter_prototype import SparkbotReadonlySpineAdapterPrototype


def _task_dict(task: SpineTask) -> dict[str, Any]:
    return task.to_dict()


def _event_dict(event: SpineEventEnvelope) -> dict[str, Any]:
    return event.to_dict()


def _project_dict(project: SpineProject) -> dict[str, Any]:
    return project.to_dict()


def _relation_dict(relation: SpineRelation) -> dict[str, Any]:
    return relation.to_dict()


def _task_list_envelope(tasks: list[SpineTask]) -> dict[str, Any]:
    return {"tasks": [_task_dict(task) for task in tasks], "count": len(tasks)}


def _event_list_envelope(events: list[SpineEventEnvelope]) -> dict[str, Any]:
    return {"events": [_event_dict(event) for event in events], "count": len(events)}


def _project_workload_envelope(projects: list[dict[str, Any]]) -> dict[str, Any]:
    return {"projects": projects, "count": len(projects)}


def _task_detail_envelope(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    if detail is None:
        return None
    return {
        "task": _task_dict(detail["task"]),
        "parent": _task_dict(detail["parent"]) if detail["parent"] is not None else None,
        "children": [_task_dict(task) for task in detail["children"]],
        "dependencies": [_task_dict(task) for task in detail["dependencies"]],
        "related": [_task_dict(task) for task in detail["related"]],
        "approvals": list(detail["approvals"]),
        "handoffs": list(detail["handoffs"]),
        "events": [_event_dict(event) for event in detail["events"]],
    }


REQUIRED_KEYS = {
    "open_queue": {"tasks", "count"},
    "blocked_queue": {"tasks", "count"},
    "approval_waiting_queue": {"tasks", "count"},
    "recent_events": {"events", "count"},
    "room_overview": {
        "room_id",
        "task_count",
        "status_counts",
        "event_count",
        "awaiting_approval_count",
        "handoff_count",
        "orphan_task_count",
        "unassigned_open_task_count",
        "project_count",
        "projects",
    },
    "project_workload": {"projects", "count"},
    "task_detail": {"task", "parent", "children", "dependencies", "related", "approvals", "handoffs", "events"},
}


def _validate_envelope(name: str, envelope: dict[str, Any] | None) -> dict[str, Any]:
    expected = REQUIRED_KEYS[name]
    actual = set(envelope.keys()) if envelope is not None else set()
    return {
        "present": envelope is not None,
        "missing_keys": sorted(expected - actual),
        "extra_keys": sorted(actual - expected),
        "valid": envelope is not None and expected.issubset(actual),
    }


def build_report(source_db: str | Path, *, room_id: str = "room-1", task_id: str = "task-1") -> dict[str, Any]:
    adapter = SparkbotReadonlySpineAdapterPrototype.from_source_db(source_db)
    try:
        open_queue = _task_list_envelope(adapter.list_open_queue(room_id=room_id))
        blocked_queue = _task_list_envelope(adapter.list_blocked_queue(room_id=room_id))
        approval_waiting_queue = _task_list_envelope(adapter.list_approval_waiting_queue(room_id=room_id))
        recent_events = _event_list_envelope(adapter.list_recent_events(room_id=room_id))
        room_overview = adapter.get_room_overview(room_id=room_id)
        project_workload = _project_workload_envelope(adapter.get_project_workload_summary(room_id=room_id))
        task_detail = _task_detail_envelope(adapter.get_task_detail(task_id=task_id))

        route_envelopes = {
            "open_queue": open_queue,
            "blocked_queue": blocked_queue,
            "approval_waiting_queue": approval_waiting_queue,
            "recent_events": recent_events,
            "room_overview": room_overview,
            "project_workload": project_workload,
            "task_detail": task_detail,
        }
        validations = {
            name: _validate_envelope(name, envelope)
            for name, envelope in route_envelopes.items()
        }
        return {
            "probe_version": 1,
            "source_db_path": str(adapter.source_db_path),
            "used_temp_copy": adapter.used_temp_copy,
            "temp_copy_path": str(adapter.temp_copy_path),
            "source_db_touched_read_only": True,
            "route_envelopes": route_envelopes,
            "route_validations": validations,
            "summary": {
                "pass": all(item["valid"] for item in validations.values()),
                "invalid_envelopes": [name for name, item in validations.items() if not item["valid"]],
            },
        }
    finally:
        adapter.close()


def write_report(source_db: str | Path, output: str | Path, *, room_id: str = "room-1", task_id: str = "task-1") -> dict[str, Any]:
    report = build_report(source_db, room_id=room_id, task_id=task_id)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sparkbot route-shape parity checks over temp-copy data")
    parser.add_argument("--source-db", required=True, help="Path to the source Sparkbot Spine SQLite DB")
    parser.add_argument("--output", required=True, help="Path to write the JSON report")
    parser.add_argument("--room-id", default="room-1", help="Room ID to probe")
    parser.add_argument("--task-id", default="task-1", help="Task ID to probe")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        write_report(args.source_db, args.output, room_id=args.room_id, task_id=args.task_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Route-shape parity failed safely: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
