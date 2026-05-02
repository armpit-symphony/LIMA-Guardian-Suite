"""Standalone SQLite Spine store for LIMA Guardian.

This module provides product-generic store semantics only. It deliberately does
not copy Sparkbot's live runtime schema or runtime behavior.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from lima_guardian.spine_interfaces import SpineStore
from lima_guardian.spine_models import (
    SpineDashboardSnapshot,
    SpineEntityType,
    SpineEventEnvelope,
    SpineProducer,
    SpineProject,
    SpineRelation,
    SpineTask,
)


CURRENT_SCHEMA_VERSION = 1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


class SQLiteSpineStore(SpineStore):
    """Generic SQLite-backed Spine store.

    TODO: Before any Sparkbot runtime integration, validate adapter mapping
    against the migrated live schema in Sparkbot's _ensure_schema_migrations()
    rather than assuming this normalized standalone schema matches it.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = OFF")
        self.init_schema()

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
        self._apply_migrations()

    def _apply_migrations(self) -> None:
        version = self._get_schema_version()
        if version > CURRENT_SCHEMA_VERSION:
            raise RuntimeError(f"Unsupported schema version: {version}")
        for target in range(version + 1, CURRENT_SCHEMA_VERSION + 1):
            migrate = getattr(self, f"_migrate_to_v{target}")
            migrate()
            self._set_schema_version(target)

    def _get_schema_version(self) -> int:
        row = self._conn.execute("SELECT MAX(version) AS version FROM schema_version").fetchone()
        return int(row["version"] or 0) if row else 0

    def _set_schema_version(self, version: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM schema_version")
            self._conn.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                (version, _utc_now_iso()),
            )

    def _migrate_to_v1(self) -> None:
        # TODO: Keep this schema generic. Sparkbot adapter work must validate
        # the live migrated schema separately before any runtime reads/writes.
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS spine_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    category TEXT NOT NULL,
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
                    payload_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    redacted INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_spine_events_room ON spine_events(room_id, occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_spine_events_task ON spine_events(task_id, occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_spine_events_project ON spine_events(project_id, occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_spine_events_subsystem ON spine_events(subsystem, occurred_at DESC);

                CREATE TABLE IF NOT EXISTS spine_tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    room_id TEXT,
                    summary TEXT,
                    project_id TEXT,
                    type TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    owner_kind TEXT NOT NULL,
                    owner_id TEXT,
                    approval_required INTEGER NOT NULL DEFAULT 0,
                    approval_state TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    parent_task_id TEXT,
                    depends_on_json TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    source_kind TEXT,
                    source_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_progress_at TEXT,
                    closed_at TEXT,
                    metadata_json TEXT NOT NULL,
                    redacted INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_spine_tasks_room ON spine_tasks(room_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_spine_tasks_project ON spine_tasks(project_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_spine_tasks_status ON spine_tasks(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS spine_projects (
                    project_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    slug TEXT,
                    room_id TEXT,
                    summary TEXT,
                    status TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    parent_project_id TEXT,
                    owner_kind TEXT,
                    owner_id TEXT,
                    created_at TEXT,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    redacted INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_spine_projects_room ON spine_projects(room_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_spine_projects_status ON spine_projects(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS spine_relations (
                    relation_id TEXT PRIMARY KEY,
                    from_entity_type TEXT NOT NULL,
                    from_entity_id TEXT NOT NULL,
                    to_entity_type TEXT NOT NULL,
                    to_entity_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    redacted INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_spine_relations_from ON spine_relations(from_entity_id, relation_type);
                CREATE INDEX IF NOT EXISTS idx_spine_relations_to ON spine_relations(to_entity_id, relation_type);

                CREATE TABLE IF NOT EXISTS spine_producers (
                    subsystem TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    event_types_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    redacted INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def append_event(self, event: SpineEventEnvelope) -> SpineEventEnvelope:
        now = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO spine_events (
                    event_id, event_type, category, occurred_at, room_id, subsystem,
                    actor_kind, actor_id, source_kind, source_ref, correlation_id,
                    task_id, project_id, payload_json, metadata_json, redacted,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.category.value,
                    event.occurred_at or now,
                    event.room_id,
                    event.subsystem,
                    event.actor_kind,
                    event.actor_id,
                    event.source_kind,
                    event.source_ref,
                    event.correlation_id,
                    event.task_id,
                    event.project_id,
                    _json_dumps(event.payload),
                    _json_dumps(event.metadata),
                    int(event.redacted),
                    now,
                    now,
                ),
            )
        return self.get_event(event.event_id) or event

    def get_event(self, event_id: str) -> SpineEventEnvelope | None:
        row = self._conn.execute(
            "SELECT * FROM spine_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return self._row_to_event(row) if row else None

    def list_events(
        self,
        *,
        room_id: str | None = None,
        task_id: str | None = None,
        project_id: str | None = None,
        subsystem: str | None = None,
        limit: int = 100,
    ) -> list[SpineEventEnvelope]:
        sql = "SELECT * FROM spine_events"
        clauses: list[str] = []
        values: list[Any] = []
        if room_id:
            clauses.append("room_id = ?")
            values.append(room_id)
        if task_id:
            clauses.append("task_id = ?")
            values.append(task_id)
        if project_id:
            clauses.append("project_id = ?")
            values.append(project_id)
        if subsystem:
            clauses.append("subsystem = ?")
            values.append(subsystem)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY occurred_at DESC LIMIT ?"
        values.append(max(1, int(limit)))
        rows = self._conn.execute(sql, values).fetchall()
        return [self._row_to_event(row) for row in rows]

    def upsert_task(self, task: SpineTask) -> SpineTask:
        now = _utc_now_iso()
        existing = self.get_task(task.task_id)
        created_at = task.created_at or (existing.created_at if existing else now)
        updated_task = SpineTask.from_dict({**task.to_dict(), "created_at": created_at, "updated_at": now})
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO spine_tasks (
                    task_id, title, room_id, summary, project_id, type, priority, status,
                    owner_kind, owner_id, approval_required, approval_state, confidence,
                    parent_task_id, depends_on_json, tags_json, source_kind, source_ref,
                    created_at, updated_at, last_progress_at, closed_at, metadata_json, redacted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    updated_task.task_id,
                    updated_task.title,
                    updated_task.room_id,
                    updated_task.summary,
                    updated_task.project_id,
                    updated_task.type,
                    updated_task.priority,
                    updated_task.status,
                    updated_task.owner_kind,
                    updated_task.owner_id,
                    int(updated_task.approval_required),
                    updated_task.approval_state,
                    updated_task.confidence,
                    updated_task.parent_task_id,
                    _json_dumps(updated_task.depends_on),
                    _json_dumps(updated_task.tags),
                    updated_task.source_kind,
                    updated_task.source_ref,
                    updated_task.created_at,
                    updated_task.updated_at,
                    updated_task.last_progress_at,
                    updated_task.closed_at,
                    _json_dumps(updated_task.metadata),
                    int(updated_task.redacted),
                ),
            )
        return self.get_task(updated_task.task_id) or updated_task

    def get_task(self, task_id: str) -> SpineTask | None:
        row = self._conn.execute(
            "SELECT * FROM spine_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(
        self,
        *,
        room_id: str | None = None,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[SpineTask]:
        sql = "SELECT * FROM spine_tasks"
        clauses: list[str] = []
        values: list[Any] = []
        if room_id:
            clauses.append("room_id = ?")
            values.append(room_id)
        if project_id:
            clauses.append("project_id = ?")
            values.append(project_id)
        if status:
            clauses.append("status = ?")
            values.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC, created_at DESC LIMIT ?"
        values.append(max(1, int(limit)))
        rows = self._conn.execute(sql, values).fetchall()
        return [self._row_to_task(row) for row in rows]

    def upsert_project(self, project: SpineProject) -> SpineProject:
        now = _utc_now_iso()
        existing = self.get_project(project.project_id)
        created_at = project.created_at or (existing.created_at if existing else now)
        updated_project = SpineProject.from_dict(
            {**project.to_dict(), "created_at": created_at, "updated_at": now}
        )
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO spine_projects (
                    project_id, display_name, slug, room_id, summary, status, tags_json,
                    parent_project_id, owner_kind, owner_id, created_at, updated_at,
                    metadata_json, redacted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    updated_project.project_id,
                    updated_project.display_name,
                    updated_project.slug,
                    updated_project.room_id,
                    updated_project.summary,
                    updated_project.status,
                    _json_dumps(updated_project.tags),
                    updated_project.parent_project_id,
                    updated_project.owner_kind,
                    updated_project.owner_id,
                    updated_project.created_at,
                    updated_project.updated_at,
                    _json_dumps(updated_project.metadata),
                    int(updated_project.redacted),
                ),
            )
        return self.get_project(updated_project.project_id) or updated_project

    def get_project(self, project_id: str) -> SpineProject | None:
        row = self._conn.execute(
            "SELECT * FROM spine_projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return self._row_to_project(row) if row else None

    def list_projects(self, *, room_id: str | None = None, limit: int = 100) -> list[SpineProject]:
        sql = "SELECT * FROM spine_projects"
        values: list[Any] = []
        if room_id:
            sql += " WHERE room_id = ?"
            values.append(room_id)
        sql += " ORDER BY updated_at DESC, created_at DESC LIMIT ?"
        values.append(max(1, int(limit)))
        rows = self._conn.execute(sql, values).fetchall()
        return [self._row_to_project(row) for row in rows]

    def record_relation(self, relation: SpineRelation) -> SpineRelation:
        created_at = relation.created_at or _utc_now_iso()
        persisted = SpineRelation.from_dict({**relation.to_dict(), "created_at": created_at})
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO spine_relations (
                    relation_id, from_entity_type, from_entity_id, to_entity_type,
                    to_entity_id, relation_type, created_at, metadata_json, redacted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    persisted.relation_id,
                    persisted.from_entity_type.value,
                    persisted.from_entity_id,
                    persisted.to_entity_type.value,
                    persisted.to_entity_id,
                    persisted.relation_type,
                    persisted.created_at,
                    _json_dumps(persisted.metadata),
                    int(persisted.redacted),
                ),
            )
        return persisted

    def list_relations(
        self,
        *,
        from_entity_id: str | None = None,
        to_entity_id: str | None = None,
        relation_type: str | None = None,
        limit: int = 200,
    ) -> list[SpineRelation]:
        sql = "SELECT * FROM spine_relations"
        clauses: list[str] = []
        values: list[Any] = []
        if from_entity_id:
            clauses.append("from_entity_id = ?")
            values.append(from_entity_id)
        if to_entity_id:
            clauses.append("to_entity_id = ?")
            values.append(to_entity_id)
        if relation_type:
            clauses.append("relation_type = ?")
            values.append(relation_type)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        values.append(max(1, int(limit)))
        rows = self._conn.execute(sql, values).fetchall()
        return [self._row_to_relation(row) for row in rows]

    def register_producer(self, producer: SpineProducer) -> SpineProducer:
        now = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO spine_producers (
                    subsystem, description, event_types_json, metadata_json,
                    redacted, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    COALESCE((SELECT created_at FROM spine_producers WHERE subsystem = ?), ?),
                    ?
                )
                """,
                (
                    producer.subsystem,
                    producer.description,
                    _json_dumps(producer.event_types),
                    _json_dumps(producer.metadata),
                    int(producer.redacted),
                    producer.subsystem,
                    now,
                    now,
                ),
            )
        return self._get_producer(producer.subsystem) or producer

    def list_producers(self) -> list[SpineProducer]:
        rows = self._conn.execute(
            "SELECT subsystem, description, event_types_json, metadata_json, redacted FROM spine_producers ORDER BY subsystem ASC"
        ).fetchall()
        return [self._row_to_producer(row) for row in rows]

    def get_dashboard_snapshot(self, *, room_id: str | None = None, limit: int = 20) -> SpineDashboardSnapshot:
        tasks = self.list_tasks(room_id=room_id, limit=limit)
        projects = self.list_projects(room_id=room_id, limit=limit)
        recent_events = self.list_events(room_id=room_id, limit=limit)

        status_counts = {
            row["status"]: int(row["count"])
            for row in self._count_status_rows(room_id=room_id)
        }
        task_count = self._count("spine_tasks", "room_id = ?", [room_id]) if room_id else self._count("spine_tasks")
        project_count = self._count("spine_projects", "room_id = ?", [room_id]) if room_id else self._count("spine_projects")
        event_count = self._count("spine_events", "room_id = ?", [room_id]) if room_id else self._count("spine_events")
        awaiting_approval_count = self._count_awaiting_approval(room_id=room_id)
        handoff_count = self._count_handoffs(room_id=room_id)
        orphan_task_count = self._count_orphan_tasks(room_id=room_id)
        unassigned_open_task_count = self._count_unassigned_open_tasks(room_id=room_id)

        return SpineDashboardSnapshot(
            room_id=room_id,
            captured_at=_utc_now_iso(),
            status_counts=status_counts,
            task_count=task_count,
            project_count=project_count,
            event_count=event_count,
            awaiting_approval_count=awaiting_approval_count,
            handoff_count=handoff_count,
            orphan_task_count=orphan_task_count,
            unassigned_open_task_count=unassigned_open_task_count,
            tasks=tasks,
            projects=projects,
            recent_events=recent_events,
            metadata={"schema_version": CURRENT_SCHEMA_VERSION},
        )

    def _count(self, table: str, where: str | None = None, values: Iterable[Any] | None = None) -> int:
        sql = f"SELECT COUNT(*) AS count FROM {table}"
        params = list(values or [])
        if where:
            sql += f" WHERE {where}"
        row = self._conn.execute(sql, params).fetchone()
        return int(row["count"] or 0) if row else 0

    def _count_status_rows(self, *, room_id: str | None) -> list[sqlite3.Row]:
        sql = "SELECT status, COUNT(*) AS count FROM spine_tasks"
        values: list[Any] = []
        if room_id:
            sql += " WHERE room_id = ?"
            values.append(room_id)
        sql += " GROUP BY status"
        return list(self._conn.execute(sql, values).fetchall())

    def _count_awaiting_approval(self, *, room_id: str | None) -> int:
        sql = (
            "SELECT COUNT(*) AS count FROM spine_tasks "
            "WHERE approval_required = 1 AND approval_state IN ('pending', 'required', 'review', 'awaiting_review')"
        )
        values: list[Any] = []
        if room_id:
            sql += " AND room_id = ?"
            values.append(room_id)
        row = self._conn.execute(sql, values).fetchone()
        return int(row["count"] or 0) if row else 0

    def _count_handoffs(self, *, room_id: str | None) -> int:
        sql = "SELECT COUNT(*) AS count FROM spine_events WHERE category = 'handoff'"
        values: list[Any] = []
        if room_id:
            sql += " AND room_id = ?"
            values.append(room_id)
        row = self._conn.execute(sql, values).fetchone()
        return int(row["count"] or 0) if row else 0

    def _count_orphan_tasks(self, *, room_id: str | None) -> int:
        sql = "SELECT COUNT(*) AS count FROM spine_tasks WHERE (project_id IS NULL OR project_id = '')"
        values: list[Any] = []
        if room_id:
            sql += " AND room_id = ?"
            values.append(room_id)
        row = self._conn.execute(sql, values).fetchone()
        return int(row["count"] or 0) if row else 0

    def _count_unassigned_open_tasks(self, *, room_id: str | None) -> int:
        sql = (
            "SELECT COUNT(*) AS count FROM spine_tasks "
            "WHERE status NOT IN ('done', 'closed', 'cancelled') "
            "AND (owner_kind IS NULL OR owner_kind = '' OR owner_kind = 'unassigned')"
        )
        values: list[Any] = []
        if room_id:
            sql += " AND room_id = ?"
            values.append(room_id)
        row = self._conn.execute(sql, values).fetchone()
        return int(row["count"] or 0) if row else 0

    def _get_producer(self, subsystem: str) -> SpineProducer | None:
        row = self._conn.execute(
            "SELECT subsystem, description, event_types_json, metadata_json, redacted FROM spine_producers WHERE subsystem = ?",
            (subsystem,),
        ).fetchone()
        return self._row_to_producer(row) if row else None

    def _row_to_event(self, row: Mapping[str, Any]) -> SpineEventEnvelope:
        return SpineEventEnvelope.from_dict(
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "category": row["category"],
                "occurred_at": row["occurred_at"],
                "room_id": row["room_id"],
                "subsystem": row["subsystem"],
                "actor_kind": row["actor_kind"],
                "actor_id": row["actor_id"],
                "source_kind": row["source_kind"],
                "source_ref": row["source_ref"],
                "correlation_id": row["correlation_id"],
                "task_id": row["task_id"],
                "project_id": row["project_id"],
                "payload": _json_loads(row["payload_json"], {}),
                "metadata": _json_loads(row["metadata_json"], {}),
                "redacted": bool(row["redacted"]),
            }
        )

    def _row_to_task(self, row: Mapping[str, Any]) -> SpineTask:
        return SpineTask.from_dict(
            {
                "task_id": row["task_id"],
                "title": row["title"],
                "room_id": row["room_id"],
                "summary": row["summary"],
                "project_id": row["project_id"],
                "type": row["type"],
                "priority": row["priority"],
                "status": row["status"],
                "owner_kind": row["owner_kind"],
                "owner_id": row["owner_id"],
                "approval_required": bool(row["approval_required"]),
                "approval_state": row["approval_state"],
                "confidence": row["confidence"],
                "parent_task_id": row["parent_task_id"],
                "depends_on": _json_loads(row["depends_on_json"], []),
                "tags": _json_loads(row["tags_json"], []),
                "source_kind": row["source_kind"],
                "source_ref": row["source_ref"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "last_progress_at": row["last_progress_at"],
                "closed_at": row["closed_at"],
                "metadata": _json_loads(row["metadata_json"], {}),
                "redacted": bool(row["redacted"]),
            }
        )

    def _row_to_project(self, row: Mapping[str, Any]) -> SpineProject:
        return SpineProject.from_dict(
            {
                "project_id": row["project_id"],
                "display_name": row["display_name"],
                "slug": row["slug"],
                "room_id": row["room_id"],
                "summary": row["summary"],
                "status": row["status"],
                "tags": _json_loads(row["tags_json"], []),
                "parent_project_id": row["parent_project_id"],
                "owner_kind": row["owner_kind"],
                "owner_id": row["owner_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "metadata": _json_loads(row["metadata_json"], {}),
                "redacted": bool(row["redacted"]),
            }
        )

    def _row_to_relation(self, row: Mapping[str, Any]) -> SpineRelation:
        return SpineRelation.from_dict(
            {
                "relation_id": row["relation_id"],
                "from_entity_type": row["from_entity_type"],
                "from_entity_id": row["from_entity_id"],
                "to_entity_type": row["to_entity_type"],
                "to_entity_id": row["to_entity_id"],
                "relation_type": row["relation_type"],
                "created_at": row["created_at"],
                "metadata": _json_loads(row["metadata_json"], {}),
                "redacted": bool(row["redacted"]),
            }
        )

    def _row_to_producer(self, row: Mapping[str, Any]) -> SpineProducer:
        return SpineProducer.from_dict(
            {
                "subsystem": row["subsystem"],
                "description": row["description"],
                "event_types": _json_loads(row["event_types_json"], []),
                "metadata": _json_loads(row["metadata_json"], {}),
                "redacted": bool(row["redacted"]),
            }
        )
