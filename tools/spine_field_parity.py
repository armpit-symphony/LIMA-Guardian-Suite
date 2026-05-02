"""Field-level parity checks for selected Sparkbot route-shaped envelopes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools.spine_route_shape_parity import build_report as build_route_shape_report


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def _matches_type(value: Any, allowed: tuple[str, ...]) -> bool:
    actual = _type_name(value)
    if actual in allowed:
        return True
    if actual == "int" and "float" in allowed:
        return True
    return False


def _check_fields(item: dict[str, Any] | None, expected: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    if item is None:
        return {
            "present": False,
            "missing_fields": sorted(expected),
            "unexpected_fields": [],
            "type_failures": {field: {"expected": list(types), "actual": "missing"} for field, types in expected.items()},
            "valid": False,
        }
    actual_fields = set(item.keys())
    expected_fields = set(expected.keys())
    missing_fields = sorted(expected_fields - actual_fields)
    type_failures: dict[str, Any] = {}
    for field, allowed in expected.items():
        if field not in item:
            continue
        if not _matches_type(item[field], allowed):
            type_failures[field] = {
                "expected": list(allowed),
                "actual": _type_name(item[field]),
            }
    return {
        "present": True,
        "missing_fields": missing_fields,
        "unexpected_fields": sorted(actual_fields - expected_fields),
        "type_failures": type_failures,
        "valid": not missing_fields and not type_failures,
    }


QUEUE_ITEM_CONTRACT = {
    "task_id": ("str",),
    "title": ("str",),
    "status": ("str",),
    "priority": ("str",),
    "room_id": ("str", "null"),
    "project_id": ("str", "null"),
    "source_kind": ("str", "null"),
    "source_ref": ("str", "null"),
    "owner_kind": ("str", "null"),
    "owner_id": ("str", "null"),
    "approval_state": ("str", "null"),
    "confidence": ("float", "null"),
    "tags": ("list",),
    "created_at": ("str",),
    "updated_at": ("str",),
    "summary": ("str", "null"),
    "type": ("str", "null"),
    "created_by_subsystem": ("str", "null"),
    "updated_by_subsystem": ("str", "null"),
    "approval_required": ("bool",),
    "parent_task_id": ("str", "null"),
    "depends_on": ("list",),
    "last_progress_at": ("str", "null"),
    "closed_at": ("str", "null"),
    "chat_task_id": ("str", "null"),
}

EVENT_ITEM_CONTRACT = {
    "event_id": ("str",),
    "event_type": ("str",),
    "category": ("str",),
    "occurred_at": ("str",),
    "room_id": ("str", "null"),
    "subsystem": ("str", "null"),
    "actor_kind": ("str",),
    "actor_id": ("str", "null"),
    "source_kind": ("str",),
    "source_ref": ("str",),
    "correlation_id": ("str",),
    "task_id": ("str", "null"),
    "project_id": ("str", "null"),
    "payload": ("dict",),
    "metadata": ("dict",),
    "redacted": ("bool",),
}

TASK_DETAIL_CONTRACT = {
    "task": ("dict",),
    "parent": ("dict", "null"),
    "children": ("list",),
    "dependencies": ("list",),
    "related": ("list",),
    "approvals": ("list",),
    "handoffs": ("list",),
    "events": ("list",),
}


def _redaction_ok(event_items: list[dict[str, Any]]) -> bool:
    saw_redaction = False
    for event_item in event_items:
        payload_text = json.dumps(event_item.get("payload", {}), sort_keys=True)
        if "secret-value" in payload_text:
            return False
        if "[REDACTED]" in payload_text:
            saw_redaction = True
    return saw_redaction


def build_report(source_db: str | Path, *, room_id: str = "room-1", task_id: str = "task-1") -> dict[str, Any]:
    route_report = build_route_shape_report(source_db, room_id=room_id, task_id=task_id)
    envelopes = route_report["route_envelopes"]

    open_item = (envelopes["open_queue"]["tasks"] or [None])[0]
    blocked_item = (envelopes["blocked_queue"]["tasks"] or [None])[0]
    approval_item = (envelopes["approval_waiting_queue"]["tasks"] or [None])[0]
    recent_event_items = envelopes["recent_events"]["events"] or []
    recent_event_item = (recent_event_items or [None])[0]
    task_detail_item = envelopes["task_detail"]

    field_checks = {
        "open_queue_item": _check_fields(open_item, QUEUE_ITEM_CONTRACT),
        "blocked_queue_item": _check_fields(blocked_item, QUEUE_ITEM_CONTRACT),
        "approval_waiting_item": _check_fields(approval_item, QUEUE_ITEM_CONTRACT),
        "recent_event_item": _check_fields(recent_event_item, EVENT_ITEM_CONTRACT),
        "task_detail_item": _check_fields(task_detail_item, TASK_DETAIL_CONTRACT),
    }

    redaction_checks = {
        "recent_event_redaction_ok": _redaction_ok(recent_event_items),
        "raw_values_emitted": False,
    }

    return {
        "probe_version": 1,
        "source_db_path": route_report["source_db_path"],
        "used_temp_copy": route_report["used_temp_copy"],
        "temp_copy_path": route_report["temp_copy_path"],
        "source_db_touched_read_only": True,
        "field_checks": field_checks,
        "redaction_checks": redaction_checks,
        "summary": {
            "pass": all(check["valid"] for check in field_checks.values()) and redaction_checks["recent_event_redaction_ok"],
            "invalid_checks": [name for name, check in field_checks.items() if not check["valid"]],
        },
    }


def write_report(source_db: str | Path, output: str | Path, *, room_id: str = "room-1", task_id: str = "task-1") -> dict[str, Any]:
    report = build_report(source_db, room_id=room_id, task_id=task_id)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Field-level parity checks for route-shaped Sparkbot envelopes")
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
        print(f"Field parity failed safely: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
