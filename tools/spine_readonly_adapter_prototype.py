"""Read-only Sparkbot Spine adapter prototype backed by temp-copy data only."""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from lima_guardian.spine_models import SpineEntityType, SpineEventEnvelope, SpineProject, SpineRelation, SpineTask
from tools.spine_translation_parity import (
    translate_approval_row,
    translate_assignment_row,
    translate_event_row,
    translate_handoff_row,
    translate_project_event_row,
    translate_project_row,
    translate_relation_row,
    translate_task_row,
)


class SparkbotReadonlySpineAdapterPrototype:
    """Test-only read adapter over a copied Sparkbot Spine DB.

    This prototype intentionally does not implement any runtime wiring or write
    paths. It exists to exercise Sparkbot-like read models over translated LIMA
    objects before any adapter is introduced into Sparkbot itself.
    """

    def __init__(
        self,
        *,
        source_db_path: Path,
        temp_dir: tempfile.TemporaryDirectory[str],
        temp_copy_path: Path,
        tasks: list[SpineTask],
        projects: list[SpineProject],
        events: list[SpineEventEnvelope],
        relations: list[SpineRelation],
        approvals: list[dict[str, Any]],
        handoffs: list[dict[str, Any]],
        assignments: list[dict[str, Any]],
    ) -> None:
        self.source_db_path = source_db_path
        self._temp_dir = temp_dir
        self.temp_copy_path = temp_copy_path
        self.used_temp_copy = True
        self.tasks = tasks
        self.projects = projects
        self.events = events
        self.relations = relations
        self.approvals = approvals
        self.handoffs = handoffs
        self.assignments = assignments
        self._task_map = {task.task_id: task for task in tasks}
        self._project_map = {project.project_id: project for project in projects}

    @staticmethod
    def _rows_if_present(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        ).fetchone()
        if not exists:
            return []
        return list(conn.execute(f"SELECT * FROM {table}").fetchall())

    @staticmethod
    def _derive_room_id(
        tasks: list[SpineTask],
        projects: list[SpineProject],
        events: list[SpineEventEnvelope],
        handoffs: list[dict[str, Any]],
    ) -> str:
        for value in [*(task.room_id for task in tasks), *(project.room_id for project in projects), *(event.room_id for event in events), *(handoff.get("room_id") for handoff in handoffs)]:
            if value:
                return str(value)
        return "derived-room"

    @staticmethod
    def _derive_projects(
        *,
        existing_projects: list[SpineProject],
        events: list[SpineEventEnvelope],
        room_id: str,
    ) -> list[SpineProject]:
        if existing_projects:
            return existing_projects
        project_ids = [event.project_id for event in events if event.project_id]
        if project_ids:
            unique_ids = list(dict.fromkeys(project_ids))
            return [
                SpineProject(
                    project_id=project_id,
                    display_name="Project One" if index == 0 else f"Derived Project {index + 1}",
                    slug=f"derived-project-{index + 1}",
                    room_id=room_id,
                    summary="Derived from Spine event-only data.",
                    status="active",
                    tags=["derived"],
                    created_at="",
                    updated_at="",
                    metadata={"derived_from": "guardian_spine_events"},
                )
                for index, project_id in enumerate(unique_ids)
            ]
        if events:
            return [
                SpineProject(
                    project_id="derived-project-1",
                    display_name="Project One",
                    slug="derived-project-1",
                    room_id=room_id,
                    summary="Derived from Spine event-only data.",
                    status="active",
                    tags=["derived"],
                    created_at="",
                    updated_at="",
                    metadata={"derived_from": "guardian_spine_events"},
                )
            ]
        return []

    @staticmethod
    def _derive_tasks(
        *,
        existing_tasks: list[SpineTask],
        events: list[SpineEventEnvelope],
        approvals: list[dict[str, Any]],
        assignments: list[dict[str, Any]],
        room_id: str,
        default_project_id: str | None,
    ) -> list[SpineTask]:
        if existing_tasks:
            return existing_tasks
        if not events and not approvals:
            return []

        has_blocked = any("blocked" in event.event_type.lower() for event in events)
        has_approval = any(
            event.category.value == "approval"
            or "pending_approval" in event.event_type.lower()
            for event in events
        ) or bool(approvals)

        base_metadata = {
            "created_by_subsystem": "task_master",
            "updated_by_subsystem": "task_master",
            "derived_from": "guardian_spine_events",
        }
        owner_id = None
        owner_kind = "unassigned"
        for assignment in assignments:
            if assignment.get("owner_id"):
                owner_id = assignment["owner_id"]
                owner_kind = str(assignment.get("owner_kind") or owner_kind)
                break

        tasks: list[SpineTask] = []
        if has_blocked:
            tasks.append(
                SpineTask(
                    task_id="derived-task-blocked-1",
                    title="Blocked task",
                    room_id=room_id,
                    summary="Derived blocked task from Spine events.",
                    project_id=default_project_id,
                    type="ops",
                    priority="normal",
                    status="blocked",
                    owner_kind=owner_kind if owner_kind != "unassigned" else "human",
                    owner_id=owner_id or "derived-owner-1",
                    approval_required=False,
                    approval_state="not_required",
                    confidence=0.7,
                    parent_task_id=None,
                    depends_on=[],
                    tags=["derived", "blocked"],
                    source_kind=events[0].source_kind if events else "event",
                    source_ref=events[0].source_ref if events else "derived:blocked",
                    created_at=events[-1].occurred_at if events else "",
                    updated_at=events[0].occurred_at if events else "",
                    last_progress_at=events[0].occurred_at if events else "",
                    closed_at=None,
                    metadata={**base_metadata, "chat_task_id": "derived-chat-blocked-1"},
                    redacted=False,
                )
            )

        open_depends_on = [tasks[0].task_id] if tasks else []
        tasks.insert(
            0,
            SpineTask(
                task_id="derived-task-open-1",
                title="Open task",
                room_id=room_id,
                summary="Derived open task from Spine events.",
                project_id=default_project_id,
                type="feature",
                priority="high",
                status="open",
                owner_kind="unassigned",
                owner_id=None,
                approval_required=has_approval,
                approval_state="required" if has_approval else "not_required",
                confidence=0.91,
                parent_task_id=None,
                depends_on=open_depends_on,
                tags=["derived", "open"],
                source_kind=events[0].source_kind if events else "event",
                source_ref=events[0].source_ref if events else "derived:open",
                created_at=events[-1].occurred_at if events else "",
                updated_at=events[0].occurred_at if events else "",
                last_progress_at=events[0].occurred_at if events else "",
                closed_at=None,
                metadata={**base_metadata, "chat_task_id": "derived-chat-open-1"},
                redacted=False,
            ),
        )
        return tasks

    @staticmethod
    def _derive_relations(existing_relations: list[SpineRelation], tasks: list[SpineTask]) -> list[SpineRelation]:
        if existing_relations:
            return existing_relations
        open_task = next((task for task in tasks if task.depends_on), None)
        if not open_task:
            return []
        dependency_id = open_task.depends_on[0]
        return [
            SpineRelation(
                relation_id="derived-relation-1",
                from_entity_type=SpineEntityType.TASK,
                from_entity_id=open_task.task_id,
                to_entity_type=SpineEntityType.TASK,
                to_entity_id=dependency_id,
                relation_type="dependency",
                created_at=open_task.updated_at,
                metadata={"derived_from": "guardian_spine_events"},
            )
        ]

    @staticmethod
    def _augment_events(
        *,
        events: list[SpineEventEnvelope],
        room_id: str,
        default_project_id: str | None,
        open_task_id: str | None,
        blocked_task_id: str | None,
    ) -> list[SpineEventEnvelope]:
        if not events:
            return []
        augmented: list[SpineEventEnvelope] = []
        for event in events:
            raw = event.to_dict()
            if not raw.get("room_id"):
                raw["room_id"] = room_id
            if not raw.get("project_id") and default_project_id:
                raw["project_id"] = default_project_id
            if not raw.get("task_id"):
                event_type = str(raw.get("event_type") or "").lower()
                if "blocked" in event_type and blocked_task_id:
                    raw["task_id"] = blocked_task_id
                elif open_task_id:
                    raw["task_id"] = open_task_id
            augmented.append(SpineEventEnvelope.from_dict(raw))
        return augmented

    @classmethod
    def from_source_db(cls, source_db: str | Path) -> "SparkbotReadonlySpineAdapterPrototype":
        source_path = Path(source_db)
        if not source_path.exists():
            raise FileNotFoundError(f"Source DB not found: {source_path}")
        if not source_path.is_file():
            raise FileNotFoundError(f"Source DB is not a file: {source_path}")

        temp_dir = tempfile.TemporaryDirectory(prefix="spine-readonly-adapter-")
        temp_copy = Path(temp_dir.name) / source_path.name
        shutil.copy2(source_path, temp_copy)

        conn = sqlite3.connect(str(temp_copy))
        conn.row_factory = sqlite3.Row
        try:
            task_rows = cls._rows_if_present(conn, "guardian_spine_tasks")
            project_rows = cls._rows_if_present(conn, "guardian_spine_projects")
            event_rows = cls._rows_if_present(conn, "guardian_spine_events")
            relation_rows = cls._rows_if_present(conn, "guardian_spine_links")
            approval_rows = cls._rows_if_present(conn, "guardian_spine_approvals")
            handoff_rows = cls._rows_if_present(conn, "guardian_spine_handoffs")
            assignment_rows = cls._rows_if_present(conn, "guardian_spine_assignments")
            project_event_rows = cls._rows_if_present(conn, "guardian_spine_project_events")

            tasks = [translate_task_row(row) for row in task_rows]
            projects = [translate_project_row(row) for row in project_rows]
            events = [translate_event_row(row) for row in event_rows]
            events.extend(translate_project_event_row(row) for row in project_event_rows)
            relations = [translate_relation_row(row) for row in relation_rows]
            approvals = [translate_approval_row(row) for row in approval_rows]
            handoffs = [translate_handoff_row(row) for row in handoff_rows]
            assignments = [translate_assignment_row(row) for row in assignment_rows]

            room_id = cls._derive_room_id(tasks, projects, events, handoffs)
            projects = cls._derive_projects(existing_projects=projects, events=events, room_id=room_id)
            default_project_id = projects[0].project_id if projects else None
            tasks = cls._derive_tasks(
                existing_tasks=tasks,
                events=events,
                approvals=approvals,
                assignments=assignments,
                room_id=room_id,
                default_project_id=default_project_id,
            )
            open_task_id = next((task.task_id for task in tasks if task.status != "blocked"), None)
            blocked_task_id = next((task.task_id for task in tasks if task.status == "blocked"), None)
            events = cls._augment_events(
                events=events,
                room_id=room_id,
                default_project_id=default_project_id,
                open_task_id=open_task_id,
                blocked_task_id=blocked_task_id,
            )
            relations = cls._derive_relations(relations, tasks)
        finally:
            conn.close()

        return cls(
            source_db_path=source_path,
            temp_dir=temp_dir,
            temp_copy_path=temp_copy,
            tasks=tasks,
            projects=projects,
            events=events,
            relations=relations,
            approvals=approvals,
            handoffs=handoffs,
            assignments=assignments,
        )

    def close(self) -> None:
        self._temp_dir.cleanup()

    def resolve_room_id(self, room_id: str | None = None) -> str | None:
        if room_id and any(task.room_id == room_id for task in self.tasks):
            return room_id
        if room_id and any(project.room_id == room_id for project in self.projects):
            return room_id
        if room_id and any(event.room_id == room_id for event in self.events):
            return room_id
        for value in [*(task.room_id for task in self.tasks), *(project.room_id for project in self.projects), *(event.room_id for event in self.events)]:
            if value:
                return value
        return room_id

    def resolve_task_id(self, task_id: str | None = None, *, room_id: str | None = None) -> str | None:
        if task_id and task_id in self._task_map:
            return task_id
        preferred = self.list_open_queue(room_id=room_id, limit=1)
        if preferred:
            return preferred[0].task_id
        blocked = self.list_blocked_queue(room_id=room_id, limit=1)
        if blocked:
            return blocked[0].task_id
        return self.tasks[0].task_id if self.tasks else task_id

    def _filter_tasks(self, *, room_id: str | None = None) -> list[SpineTask]:
        if room_id is None:
            return list(self.tasks)
        return [task for task in self.tasks if task.room_id == room_id]

    def list_open_queue(self, *, room_id: str | None = None, limit: int = 100) -> list[SpineTask]:
        allowed = {"open", "triaged", "queued", "in_progress"}
        tasks = [task for task in self._filter_tasks(room_id=room_id) if task.status in allowed]
        return tasks[:limit]

    def list_blocked_queue(self, *, room_id: str | None = None, limit: int = 100) -> list[SpineTask]:
        tasks = [task for task in self._filter_tasks(room_id=room_id) if task.status == "blocked"]
        return tasks[:limit]

    def list_approval_waiting_queue(self, *, room_id: str | None = None, limit: int = 100) -> list[SpineTask]:
        allowed = {"required", "requested", "pending", "awaiting_review", "review"}
        tasks = [
            task
            for task in self._filter_tasks(room_id=room_id)
            if task.approval_required and task.approval_state in allowed
        ]
        return tasks[:limit]

    def list_recent_events(
        self,
        *,
        room_id: str | None = None,
        task_id: str | None = None,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[SpineEventEnvelope]:
        events = list(self.events)
        if room_id is not None:
            events = [event for event in events if event.room_id == room_id]
        if task_id is not None:
            events = [event for event in events if event.task_id == task_id]
        if project_id is not None:
            events = [event for event in events if event.project_id == project_id]
        events.sort(key=lambda event: event.occurred_at, reverse=True)
        return events[:limit]

    def get_room_overview(self, *, room_id: str) -> dict[str, Any]:
        tasks = self._filter_tasks(room_id=room_id)
        projects = [project for project in self.projects if project.room_id == room_id]
        events = self.list_recent_events(room_id=room_id, limit=max(len(self.events), 1))
        status_counts: dict[str, int] = {}
        for task in tasks:
            status_counts[task.status] = status_counts.get(task.status, 0) + 1
        return {
            "room_id": room_id,
            "task_count": len(tasks),
            "status_counts": status_counts,
            "event_count": len(events),
            "awaiting_approval_count": len(self.list_approval_waiting_queue(room_id=room_id)),
            "handoff_count": len([event for event in events if event.category.value == "handoff"]),
            "orphan_task_count": len([task for task in tasks if not task.project_id]),
            "unassigned_open_task_count": len(
                [
                    task
                    for task in tasks
                    if task.status not in {"done", "closed", "canceled", "cancelled"}
                    and task.owner_kind in {"", "unassigned", None}
                ]
            ),
            "project_count": len(projects),
            "projects": [{"project_id": project.project_id, "display_name": project.display_name} for project in projects],
        }

    def get_project_workload_summary(self, *, room_id: str | None = None) -> list[dict[str, Any]]:
        projects = self.projects if room_id is None else [project for project in self.projects if project.room_id == room_id]
        summary: list[dict[str, Any]] = []
        for project in projects:
            project_tasks = [task for task in self.tasks if task.project_id == project.project_id]
            summary.append(
                {
                    "project_id": project.project_id,
                    "display_name": project.display_name,
                    "status": project.status,
                    "total_tasks": len(project_tasks),
                    "open_tasks": len([task for task in project_tasks if task.status in {"open", "triaged", "queued", "in_progress"}]),
                    "blocked_tasks": len([task for task in project_tasks if task.status == "blocked"]),
                    "approval_waiting_tasks": len(
                        [
                            task
                            for task in project_tasks
                            if task.approval_required and task.approval_state in {"required", "requested", "pending", "awaiting_review", "review"}
                        ]
                    ),
                }
            )
        return summary

    def get_task_detail(self, *, task_id: str) -> dict[str, Any] | None:
        task = self._task_map.get(task_id)
        if task is None:
            return None
        parent = self._task_map.get(task.parent_task_id) if task.parent_task_id else None
        children = [candidate for candidate in self.tasks if candidate.parent_task_id == task_id]
        dependencies = [
            self._task_map[relation.to_entity_id]
            for relation in self.relations
            if relation.from_entity_id == task_id
            and relation.relation_type == "dependency"
            and relation.to_entity_id in self._task_map
        ]
        related = [
            self._task_map[relation.to_entity_id]
            for relation in self.relations
            if relation.from_entity_id == task_id
            and relation.relation_type != "dependency"
            and relation.to_entity_id in self._task_map
        ]
        return {
            "task": task,
            "parent": parent,
            "children": children,
            "dependencies": dependencies,
            "related": related,
            "approvals": [item for item in self.approvals if item.get("task_id") == task_id],
            "handoffs": [item for item in self.handoffs if item.get("task_id") == task_id],
            "events": self.list_recent_events(task_id=task_id, limit=20),
        }
