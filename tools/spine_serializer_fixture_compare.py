"""Compare route-shaped envelopes to sanitized expected fixtures."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools.spine_route_shape_parity import build_report as build_route_shape_report


VOLATILE_TIMESTAMP_KEYS = {"created_at", "updated_at", "last_progress_at", "occurred_at"}
VOLATILE_ID_KEYS = {
    "task_id",
    "project_id",
    "room_id",
    "owner_id",
    "chat_task_id",
    "event_id",
    "correlation_id",
}
VOLATILE_REF_KEYS = {"source_ref"}
VOLATILE_ID_LIST_KEYS = {"depends_on"}
GENERIC_STRING_KEYS = {
    "title",
    "summary",
    "status",
    "priority",
    "type",
    "source_kind",
    "owner_kind",
    "approval_state",
    "created_by_subsystem",
    "updated_by_subsystem",
    "event_type",
    "category",
    "subsystem",
    "actor_kind",
}
GENERIC_NUMBER_KEYS = {"confidence"}


def _normalize(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        if key == "payload":
            return {}
        return {k: _normalize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        if key in VOLATILE_ID_LIST_KEYS:
            return ["<id>" if isinstance(item, str) else _normalize(item, key) for item in value]
        if key == "tags":
            return ["<str>" if isinstance(item, str) else _normalize(item, key) for item in value]
        return [_normalize(item, key) for item in value]
    if isinstance(value, str):
        if key in VOLATILE_TIMESTAMP_KEYS:
            return "<timestamp>"
        if key in VOLATILE_ID_KEYS:
            return "<id>"
        if key in VOLATILE_REF_KEYS:
            return "<ref>"
        if key in GENERIC_STRING_KEYS:
            return "<str>"
    if isinstance(value, (int, float)) and key in GENERIC_NUMBER_KEYS:
        return "<number>"
    return value


def _compare_subset(expected: Any, actual: Any, path: str = "") -> list[str]:
    mismatches: list[str] = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [path or "$"]
        for key, expected_value in expected.items():
            if key not in actual:
                mismatches.append(f"{path}.{key}" if path else key)
                continue
            next_path = f"{path}.{key}" if path else key
            mismatches.extend(_compare_subset(expected_value, actual[key], next_path))
        return mismatches
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) < len(expected):
            return [path or "$"]
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            mismatches.extend(_compare_subset(expected_item, actual_item, f"{path}[{index}]"))
        return mismatches
    if expected != actual:
        return [path or "$"]
    return mismatches


def _load_fixture(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_preview(actual: Any, expected: Any) -> Any:
    if isinstance(expected, dict) and isinstance(actual, dict):
        return {key: _safe_preview(actual.get(key), value) for key, value in expected.items() if key in actual}
    if isinstance(expected, list) and isinstance(actual, list):
        return [_safe_preview(a, e) for a, e in zip(actual, expected)]
    return actual


def build_report(source_db: str | Path, fixture_dir: str | Path, *, room_id: str = "room-1", task_id: str = "task-1") -> dict[str, Any]:
    route_report = build_route_shape_report(source_db, room_id=room_id, task_id=task_id)
    fixture_root = Path(fixture_dir)

    targets = {
        "open_queue": route_report["route_envelopes"]["open_queue"],
        "task_detail": route_report["route_envelopes"]["task_detail"],
    }

    comparisons: dict[str, Any] = {}
    for name, actual in targets.items():
        fixture_path = fixture_root / f"{name}.json"
        expected = _load_fixture(fixture_path)
        normalized_actual = _normalize(actual)
        normalized_expected = _normalize(expected)
        mismatches = _compare_subset(normalized_expected, normalized_actual)
        preview = _safe_preview(normalized_actual, normalized_expected)
        preview_text = json.dumps(preview, sort_keys=True)
        if "secret-value" in preview_text:
            raise ValueError("Unsafe secret value detected in normalized preview")
        comparisons[name] = {
            "fixture_path": str(fixture_path),
            "match": not mismatches,
            "mismatched_paths": mismatches,
            "normalized_preview": preview,
        }

    return {
        "probe_version": 1,
        "source_db_path": route_report["source_db_path"],
        "used_temp_copy": route_report["used_temp_copy"],
        "temp_copy_path": route_report["temp_copy_path"],
        "source_db_touched_read_only": True,
        "comparisons": comparisons,
        "summary": {
            "pass": all(item["match"] for item in comparisons.values()),
            "failed_comparisons": [name for name, item in comparisons.items() if not item["match"]],
        },
    }


def write_report(source_db: str | Path, fixture_dir: str | Path, output: str | Path, *, room_id: str = "room-1", task_id: str = "task-1") -> dict[str, Any]:
    report = build_report(source_db, fixture_dir, room_id=room_id, task_id=task_id)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare route-shaped envelopes to sanitized serializer fixtures")
    parser.add_argument("--source-db", required=True, help="Path to the source Sparkbot Spine SQLite DB")
    parser.add_argument("--fixture-dir", required=True, help="Directory containing expected fixture JSON")
    parser.add_argument("--output", required=True, help="Path to write the JSON report")
    parser.add_argument("--room-id", default="room-1", help="Room ID to probe")
    parser.add_argument("--task-id", default="task-1", help="Task ID to probe")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        write_report(args.source_db, args.fixture_dir, args.output, room_id=args.room_id, task_id=args.task_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Serializer fixture comparison failed safely: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
