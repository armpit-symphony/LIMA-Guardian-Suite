"""Temp-copy-only Sparkbot Spine to LIMA translation parity harness."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from lima_guardian.spine_events import redact_sensitive
from lima_guardian.spine_models import (
    SpineEntityType,
    SpineEventEnvelope,
    SpineEventType,
    SpineProducer,
    SpineProject,
    SpineRelation,
    SpineTask,
)


SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "auth_token",
    "private_key",
    "vault_key",
    "pin",
)


def _row_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return dict(row)


def _safe_json_load(raw: str | None, fallback: Any) -> tuple[Any, bool]:
    if not raw:
        return fallback, False
    try:
        return json.loads(raw), False
    except Exception:
        return fallback, True


def _classify_event(*, event_type: str | None, subsystem: str | None, task_id: str | None, project_id: str | None) -> SpineEventType:
    text = f"{event_type or ''} {subsystem or ''}".lower()
    if "approval" in text:
        return SpineEventType.APPROVAL
    if "breakglass" in text or "security" in text:
        return SpineEventType.SECURITY
    if "meeting" in text:
        return SpineEventType.MEETING
    if "handoff" in text:
        return SpineEventType.HANDOFF
    if "project" in text or project_id:
        return SpineEventType.PROJECT
    if "worker" in text:
        return SpineEventType.WORKER
    if "verif" in text:
        return SpineEventType.VERIFIER
    if "executive" in text:
        return SpineEventType.EXECUTIVE
    if "memory" in text:
        return SpineEventType.MEMORY
    if "scheduled" in text or "scheduler" in text:
        return SpineEventType.SCHEDULED_JOB
    if task_id:
        return SpineEventType.TASK
    return SpineEventType.OTHER


def _safe_metadata(metadata: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    raw = dict(metadata)
    redacted = redact_sensitive(raw)
    return redacted, redacted != raw


def _field_names_for_model(model: Any) -> list[str]:
    return sorted(model.to_dict().keys())


def translate_task_row(row: Mapping[str, Any]) -> SpineTask:
    raw = _row_dict(row)
    depends_on, _ = _safe_json_load(raw.get("depends_on_json"), [])
    tags, _ = _safe_json_load(raw.get("tags_json"), [])
    metadata, redacted = _safe_metadata(
        {
            "created_by_guardian": raw.get("created_by_guardian"),
            "created_by_subsystem": raw.get("created_by_subsystem"),
            "updated_by_subsystem": raw.get("updated_by_subsystem"),
            "chat_task_id": raw.get("chat_task_id"),
            "source_excerpt_present": bool(raw.get("source_excerpt")),
        }
    )
    return SpineTask(
        task_id=str(raw.get("task_id") or ""),
        title=str(raw.get("title") or ""),
        room_id=raw.get("room_id"),
        summary=raw.get("summary"),
        project_id=raw.get("project_id"),
        type=str(raw.get("type") or "feature"),
        priority=str(raw.get("priority") or "normal"),
        status=str(raw.get("status") or "open"),
        owner_kind=str(raw.get("owner_kind") or "unassigned"),
        owner_id=raw.get("owner_id"),
        approval_required=bool(raw.get("approval_required", False)),
        approval_state=str(raw.get("approval_state") or "not_required"),
        confidence=float(raw.get("confidence") or 0.0) if raw.get("confidence") is not None else 1.0,
        parent_task_id=raw.get("parent_task_id"),
        depends_on=depends_on if isinstance(depends_on, list) else [],
        tags=tags if isinstance(tags, list) else [],
        source_kind=raw.get("source_kind"),
        source_ref=raw.get("source_ref"),
        created_at=str(raw.get("created_at") or ""),
        updated_at=str(raw.get("updated_at") or ""),
        last_progress_at=raw.get("last_progress_at"),
        closed_at=raw.get("closed_at"),
        metadata=metadata,
        redacted=redacted,
    )


def translate_project_row(row: Mapping[str, Any]) -> SpineProject:
    raw = _row_dict(row)
    tags, _ = _safe_json_load(raw.get("tags_json"), [])
    metadata, redacted = _safe_metadata(
        {
            "source_kind": raw.get("source_kind"),
            "source_ref": raw.get("source_ref"),
            "created_by_subsystem": raw.get("created_by_subsystem"),
            "updated_by_subsystem": raw.get("updated_by_subsystem"),
        }
    )
    return SpineProject(
        project_id=str(raw.get("project_id") or ""),
        display_name=str(raw.get("display_name") or ""),
        slug=raw.get("slug"),
        room_id=raw.get("room_id"),
        summary=raw.get("summary"),
        status=str(raw.get("status") or "active"),
        tags=tags if isinstance(tags, list) else [],
        parent_project_id=raw.get("parent_project_id"),
        owner_kind=raw.get("owner_kind"),
        owner_id=raw.get("owner_id"),
        created_at=raw.get("created_at"),
        updated_at=str(raw.get("updated_at") or ""),
        metadata=metadata,
        redacted=redacted,
    )


def translate_event_row(row: Mapping[str, Any]) -> SpineEventEnvelope:
    raw = _row_dict(row)
    payload, invalid_json = _safe_json_load(raw.get("payload_json"), {})
    if invalid_json or not isinstance(payload, dict):
        payload = {}
    redacted_payload = redact_sensitive(payload)
    return SpineEventEnvelope(
        event_id=str(raw.get("event_id") or ""),
        event_type=str(raw.get("event_type") or ""),
        category=_classify_event(
            event_type=raw.get("event_type"),
            subsystem=raw.get("subsystem"),
            task_id=raw.get("task_id"),
            project_id=raw.get("project_id"),
        ),
        occurred_at=str(raw.get("occurred_at") or ""),
        room_id=raw.get("room_id"),
        subsystem=raw.get("subsystem"),
        actor_kind=str(raw.get("actor_kind") or "system"),
        actor_id=raw.get("actor_id"),
        source_kind=str(raw.get("source_kind") or "system"),
        source_ref=str(raw.get("source_ref") or ""),
        correlation_id=str(raw.get("correlation_id") or ""),
        task_id=raw.get("task_id"),
        project_id=raw.get("project_id"),
        payload=redacted_payload,
        metadata={},
        redacted=redacted_payload != payload,
    )


def translate_relation_row(row: Mapping[str, Any]) -> SpineRelation:
    raw = _row_dict(row)
    return SpineRelation(
        relation_id=str(raw.get("id") or raw.get("relation_id") or ""),
        from_entity_type=SpineEntityType.TASK,
        from_entity_id=str(raw.get("task_id") or raw.get("from_entity_id") or ""),
        to_entity_type=SpineEntityType.TASK,
        to_entity_id=str(raw.get("related_task_id") or raw.get("to_entity_id") or ""),
        relation_type=str(raw.get("link_type") or raw.get("relation_type") or ""),
        created_at=str(raw.get("created_at") or ""),
        metadata={},
        redacted=False,
    )


def translate_producer_rows(rows: list[Mapping[str, Any]]) -> list[SpineProducer]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        raw = _row_dict(row)
        subsystem = str(raw.get("subsystem") or "").strip()
        if not subsystem:
            continue
        grouped.setdefault(
            subsystem,
            {"subsystem": subsystem, "description": "Derived via event subsystem scan.", "event_types": set()},
        )
        event_type = str(raw.get("event_type") or "").strip()
        if event_type:
            grouped[subsystem]["event_types"].add(event_type)
    return [
        SpineProducer(
            subsystem=data["subsystem"],
            description=data["description"],
            event_types=sorted(data["event_types"]),
            metadata={"derived_from": "guardian_spine_events"},
        )
        for _, data in sorted(grouped.items())
    ]


def _rows(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    return list(conn.execute(query).fetchall())


def _rows_if_present(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    if not exists:
        return []
    return _rows(conn, f"SELECT * FROM {table}")


def _translate_many(rows: list[Mapping[str, Any]], translator) -> tuple[int, int, list[Any]]:
    success = 0
    failure = 0
    translated: list[Any] = []
    for row in rows:
        try:
            translated.append(translator(row))
            success += 1
        except Exception:
            failure += 1
    return success, failure, translated


def translate_assignment_row(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = _row_dict(row)
    metadata, redacted = _safe_metadata(
        {
            "owner_kind": raw.get("owner_kind"),
            "owner_id": raw.get("owner_id"),
            "assigned_by": raw.get("assigned_by"),
        }
    )
    return {
        "assignment_id": str(raw.get("id") or ""),
        "task_id": str(raw.get("task_id") or ""),
        "owner_kind": str(raw.get("owner_kind") or "unassigned"),
        "owner_id": raw.get("owner_id"),
        "assigned_at": str(raw.get("assigned_at") or ""),
        "metadata": metadata,
        "redacted": redacted,
    }


def translate_approval_row(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = _row_dict(row)
    scope, _ = _safe_json_load(raw.get("scope_json"), [])
    metadata, redacted = _safe_metadata(
        {
            "requester_id": raw.get("requester_id"),
            "approver_id": raw.get("approver_id"),
            "approval_method": raw.get("approval_method"),
        }
    )
    return {
        "approval_id": str(raw.get("id") or ""),
        "task_id": str(raw.get("task_id") or ""),
        "state": str(raw.get("state") or "pending"),
        "scope": scope if isinstance(scope, list) else [],
        "expires_at": raw.get("expires_at"),
        "created_at": str(raw.get("created_at") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
        "metadata": metadata,
        "redacted": redacted,
    }


def translate_handoff_row(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = _row_dict(row)
    metadata, redacted = _safe_metadata({"source_ref": raw.get("source_ref")})
    return {
        "handoff_id": str(raw.get("id") or ""),
        "task_id": str(raw.get("task_id") or ""),
        "room_id": raw.get("room_id"),
        "summary": str(raw.get("summary") or ""),
        "created_at": str(raw.get("created_at") or ""),
        "metadata": metadata,
        "redacted": redacted,
    }


def translate_project_event_row(row: Mapping[str, Any]) -> SpineEventEnvelope:
    raw = _row_dict(row)
    payload, invalid_json = _safe_json_load(raw.get("payload_json"), {})
    if invalid_json or not isinstance(payload, dict):
        payload = {}
    redacted_payload = redact_sensitive(payload)
    return SpineEventEnvelope(
        event_id=str(raw.get("event_id") or ""),
        event_type=str(raw.get("event_type") or ""),
        category=SpineEventType.PROJECT,
        occurred_at=str(raw.get("occurred_at") or ""),
        room_id=raw.get("room_id"),
        subsystem=raw.get("subsystem"),
        actor_kind="system",
        actor_id=None,
        source_kind=str(raw.get("source_kind") or "project"),
        source_ref=str(raw.get("source_ref") or ""),
        correlation_id=str(raw.get("event_id") or ""),
        task_id=None,
        project_id=raw.get("project_id"),
        payload=redacted_payload,
        metadata={},
        redacted=redacted_payload != payload,
    )


def build_report(source_db: str | Path) -> dict[str, Any]:
    source_path = Path(source_db)
    if not source_path.exists():
        raise FileNotFoundError(f"Source DB not found: {source_path}")
    if not source_path.is_file():
        raise FileNotFoundError(f"Source DB is not a file: {source_path}")

    with tempfile.TemporaryDirectory(prefix="spine-translation-") as temp_dir:
        temp_path = Path(temp_dir) / source_path.name
        shutil.copy2(source_path, temp_path)
        conn = sqlite3.connect(str(temp_path))
        conn.row_factory = sqlite3.Row
        try:
            task_rows = _rows_if_present(conn, "guardian_spine_tasks")
            project_rows = _rows_if_present(conn, "guardian_spine_projects")
            event_rows = _rows_if_present(conn, "guardian_spine_events")
            relation_rows = _rows_if_present(conn, "guardian_spine_links")
            assignment_rows = _rows_if_present(conn, "guardian_spine_assignments")
            approval_rows = _rows_if_present(conn, "guardian_spine_approvals")
            handoff_rows = _rows_if_present(conn, "guardian_spine_handoffs")
            project_event_rows = _rows_if_present(conn, "guardian_spine_project_events")

            task_success, task_failure, tasks = _translate_many(task_rows, translate_task_row)
            project_success, project_failure, projects = _translate_many(project_rows, translate_project_row)
            event_success, event_failure, events = _translate_many(event_rows, translate_event_row)
            relation_success, relation_failure, relations = _translate_many(relation_rows, translate_relation_row)
            assignment_success, assignment_failure, assignments = _translate_many(assignment_rows, translate_assignment_row)
            approval_success, approval_failure, approvals = _translate_many(approval_rows, translate_approval_row)
            handoff_success, handoff_failure, handoffs = _translate_many(handoff_rows, translate_handoff_row)
            project_event_success, project_event_failure, project_events = _translate_many(
                project_event_rows,
                translate_project_event_row,
            )
            producers = translate_producer_rows(event_rows)

            raw_rows_with_sensitive_keys = 0
            translated_redacted_events = 0
            for event in [*events, *project_events]:
                payload_text = json.dumps(event.payload, sort_keys=True)
                if any(part in payload_text.lower() for part in SENSITIVE_KEY_PARTS):
                    raw_rows_with_sensitive_keys += 1
                if event.redacted:
                    translated_redacted_events += 1

            report = {
                "probe_version": 1,
                "source_db_path": str(source_path),
                "used_temp_copy": True,
                "temp_copy_path": str(temp_path),
                "source_db_touched_read_only": True,
                "translation_counts": {
                    "tasks": {"success": task_success, "failure": task_failure},
                    "projects": {"success": project_success, "failure": project_failure},
                    "events": {"success": event_success, "failure": event_failure},
                    "relations": {"success": relation_success, "failure": relation_failure},
                    "assignments": {"success": assignment_success, "failure": assignment_failure},
                    "approvals": {"success": approval_success, "failure": approval_failure},
                    "handoffs": {"success": handoff_success, "failure": handoff_failure},
                    "project_events": {"success": project_event_success, "failure": project_event_failure},
                    "producers": {"success": len(producers), "failure": 0},
                },
                "field_parity": {
                    "task": {
                        "source_fields": sorted(task_rows[0].keys()) if task_rows else [],
                        "translated_fields": _field_names_for_model(tasks[0]) if tasks else [],
                        "sparkbot_only_fields": [
                            "created_by_guardian",
                            "created_by_subsystem",
                            "updated_by_subsystem",
                            "source_excerpt",
                            "chat_task_id",
                        ],
                    },
                    "project": {
                        "source_fields": sorted(project_rows[0].keys()) if project_rows else [],
                        "translated_fields": _field_names_for_model(projects[0]) if projects else [],
                        "sparkbot_only_fields": [
                            "source_kind",
                            "source_ref",
                            "created_by_subsystem",
                            "updated_by_subsystem",
                        ],
                    },
                    "event": {
                        "source_fields": sorted(event_rows[0].keys()) if event_rows else [],
                        "translated_fields": _field_names_for_model(events[0]) if events else [],
                        "derived_fields": ["category", "metadata", "redacted"],
                    },
                    "relation": {
                        "source_fields": sorted(relation_rows[0].keys()) if relation_rows else [],
                        "translated_fields": _field_names_for_model(relations[0]) if relations else [],
                        "derived_fields": ["from_entity_type", "to_entity_type"],
                    },
                    "assignment": {
                        "source_fields": sorted(assignment_rows[0].keys()) if assignment_rows else [],
                        "translated_fields": sorted(assignments[0].keys()) if assignments else [],
                    },
                    "approval": {
                        "source_fields": sorted(approval_rows[0].keys()) if approval_rows else [],
                        "translated_fields": sorted(approvals[0].keys()) if approvals else [],
                    },
                    "handoff": {
                        "source_fields": sorted(handoff_rows[0].keys()) if handoff_rows else [],
                        "translated_fields": sorted(handoffs[0].keys()) if handoffs else [],
                    },
                    "project_event": {
                        "source_fields": sorted(project_event_rows[0].keys()) if project_event_rows else [],
                        "translated_fields": _field_names_for_model(project_events[0]) if project_events else [],
                    },
                },
                "redaction_checks": {
                    "translated_redacted_events": translated_redacted_events,
                    "translated_rows_with_sensitive_keys": raw_rows_with_sensitive_keys,
                    "raw_values_emitted": False,
                },
                "limitations": [
                    "Producer translations are derived from event subsystems, not a persisted producer table.",
                ],
            }
            report["summary"] = {
                "pass": all(
                    count["failure"] == 0
                    for count in report["translation_counts"].values()
                ),
                "translated_models": sum(count["success"] for count in report["translation_counts"].values()),
                "translation_failures": sum(count["failure"] for count in report["translation_counts"].values()),
            }
            return report
        finally:
            conn.close()


def write_report(source_db: str | Path, output: str | Path) -> dict[str, Any]:
    report = build_report(source_db)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sparkbot Spine translation parity harness")
    parser.add_argument("--source-db", required=True, help="Path to the source Sparkbot Spine SQLite DB")
    parser.add_argument("--output", required=True, help="Path to write the JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        write_report(args.source_db, args.output)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Translation parity failed safely: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
