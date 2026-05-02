"""Product-generic Spine models for LIMA Guardian.

Contracts only: these models deliberately avoid Sparkbot-specific dependencies.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping


class SpineEventType(str, Enum):
    TASK = "task"
    PROJECT = "project"
    APPROVAL = "approval"
    HANDOFF = "handoff"
    MEMORY = "memory"
    MEETING = "meeting"
    SECURITY = "security"
    WORKER = "worker"
    ROOM_LIFECYCLE = "room_lifecycle"
    EXECUTIVE = "executive"
    VERIFIER = "verifier"
    SCHEDULED_JOB = "scheduled_job"
    OTHER = "other"


class SpineEntityType(str, Enum):
    TASK = "task"
    PROJECT = "project"
    EVENT = "event"
    APPROVAL = "approval"
    HANDOFF = "handoff"
    RELATION = "relation"
    PRODUCER = "producer"
    DASHBOARD_SNAPSHOT = "dashboard_snapshot"


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_list_str(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        items = [str(v).strip() for v in value if str(v).strip()]
        # Stable order without losing intent.
        return list(dict.fromkeys(items))
    return [str(value).strip()] if str(value).strip() else []


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    return {"value": value}


@dataclass(frozen=True)
class SpineEventEnvelope:
    event_id: str
    event_type: str
    category: SpineEventType = SpineEventType.OTHER
    occurred_at: str = ""
    room_id: str | None = None
    subsystem: str | None = None
    actor_kind: str = "system"
    actor_id: str | None = None
    source_kind: str = "system"
    source_ref: str = ""
    correlation_id: str = ""
    task_id: str | None = None
    project_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    redacted: bool = False

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["category"] = self.category.value
        return out

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SpineEventEnvelope":
        category_raw = str(raw.get("category") or SpineEventType.OTHER.value).strip().lower()
        try:
            category = SpineEventType(category_raw)
        except Exception:
            category = SpineEventType.OTHER
        return cls(
            event_id=str(raw.get("event_id") or ""),
            event_type=str(raw.get("event_type") or ""),
            category=category,
            occurred_at=str(raw.get("occurred_at") or ""),
            room_id=_coerce_str(raw.get("room_id")),
            subsystem=_coerce_str(raw.get("subsystem")),
            actor_kind=str(raw.get("actor_kind") or "system"),
            actor_id=_coerce_str(raw.get("actor_id")),
            source_kind=str(raw.get("source_kind") or "system"),
            source_ref=str(raw.get("source_ref") or ""),
            correlation_id=str(raw.get("correlation_id") or ""),
            task_id=_coerce_str(raw.get("task_id")),
            project_id=_coerce_str(raw.get("project_id")),
            payload=_coerce_dict(raw.get("payload")),
            metadata=_coerce_dict(raw.get("metadata")),
            redacted=bool(raw.get("redacted", False)),
        )


@dataclass(frozen=True)
class SpineTask:
    task_id: str
    title: str
    room_id: str | None = None
    summary: str | None = None
    project_id: str | None = None
    type: str = "feature"
    priority: str = "normal"
    status: str = "open"
    owner_kind: str = "unassigned"
    owner_id: str | None = None
    approval_required: bool = False
    approval_state: str = "not_required"
    confidence: float = 1.0
    parent_task_id: str | None = None
    depends_on: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    source_kind: str | None = None
    source_ref: str | None = None
    created_at: str = ""
    updated_at: str = ""
    last_progress_at: str | None = None
    closed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    redacted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SpineTask":
        return cls(
            task_id=str(raw.get("task_id") or ""),
            title=str(raw.get("title") or ""),
            room_id=_coerce_str(raw.get("room_id")),
            summary=_coerce_str(raw.get("summary")),
            project_id=_coerce_str(raw.get("project_id")),
            type=str(raw.get("type") or "feature"),
            priority=str(raw.get("priority") or "normal"),
            status=str(raw.get("status") or "open"),
            owner_kind=str(raw.get("owner_kind") or "unassigned"),
            owner_id=_coerce_str(raw.get("owner_id")),
            approval_required=bool(raw.get("approval_required", False)),
            approval_state=str(raw.get("approval_state") or "not_required"),
            confidence=float(raw.get("confidence") or 0.0) if raw.get("confidence") is not None else 1.0,
            parent_task_id=_coerce_str(raw.get("parent_task_id")),
            depends_on=_coerce_list_str(raw.get("depends_on")),
            tags=_coerce_list_str(raw.get("tags")),
            source_kind=_coerce_str(raw.get("source_kind")),
            source_ref=_coerce_str(raw.get("source_ref")),
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
            last_progress_at=_coerce_str(raw.get("last_progress_at")),
            closed_at=_coerce_str(raw.get("closed_at")),
            metadata=_coerce_dict(raw.get("metadata")),
            redacted=bool(raw.get("redacted", False)),
        )


@dataclass(frozen=True)
class SpineProject:
    project_id: str
    display_name: str
    slug: str | None = None
    room_id: str | None = None
    summary: str | None = None
    status: str = "active"
    tags: list[str] = field(default_factory=list)
    parent_project_id: str | None = None
    owner_kind: str | None = None
    owner_id: str | None = None
    created_at: str | None = None
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    redacted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SpineProject":
        return cls(
            project_id=str(raw.get("project_id") or ""),
            display_name=str(raw.get("display_name") or ""),
            slug=_coerce_str(raw.get("slug")),
            room_id=_coerce_str(raw.get("room_id")),
            summary=_coerce_str(raw.get("summary")),
            status=str(raw.get("status") or "active"),
            tags=_coerce_list_str(raw.get("tags")),
            parent_project_id=_coerce_str(raw.get("parent_project_id")),
            owner_kind=_coerce_str(raw.get("owner_kind")),
            owner_id=_coerce_str(raw.get("owner_id")),
            created_at=_coerce_str(raw.get("created_at")),
            updated_at=str(raw.get("updated_at") or ""),
            metadata=_coerce_dict(raw.get("metadata")),
            redacted=bool(raw.get("redacted", False)),
        )


@dataclass(frozen=True)
class SpineProducer:
    subsystem: str
    description: str = ""
    event_types: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    redacted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SpineProducer":
        return cls(
            subsystem=str(raw.get("subsystem") or ""),
            description=str(raw.get("description") or ""),
            event_types=_coerce_list_str(raw.get("event_types")),
            metadata=_coerce_dict(raw.get("metadata")),
            redacted=bool(raw.get("redacted", False)),
        )


@dataclass(frozen=True)
class SpineRelation:
    relation_id: str
    from_entity_type: SpineEntityType
    from_entity_id: str
    to_entity_type: SpineEntityType
    to_entity_id: str
    relation_type: str
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    redacted: bool = False

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["from_entity_type"] = self.from_entity_type.value
        out["to_entity_type"] = self.to_entity_type.value
        return out

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SpineRelation":
        def _entity_type(value: Any) -> SpineEntityType:
            try:
                return SpineEntityType(str(value or "").strip().lower())
            except Exception:
                return SpineEntityType.EVENT

        return cls(
            relation_id=str(raw.get("relation_id") or ""),
            from_entity_type=_entity_type(raw.get("from_entity_type")),
            from_entity_id=str(raw.get("from_entity_id") or ""),
            to_entity_type=_entity_type(raw.get("to_entity_type")),
            to_entity_id=str(raw.get("to_entity_id") or ""),
            relation_type=str(raw.get("relation_type") or ""),
            created_at=str(raw.get("created_at") or ""),
            metadata=_coerce_dict(raw.get("metadata")),
            redacted=bool(raw.get("redacted", False)),
        )


@dataclass(frozen=True)
class SpineDashboardSnapshot:
    room_id: str | None
    captured_at: str
    status_counts: dict[str, int] = field(default_factory=dict)
    task_count: int = 0
    project_count: int = 0
    event_count: int = 0
    awaiting_approval_count: int = 0
    handoff_count: int = 0
    orphan_task_count: int = 0
    unassigned_open_task_count: int = 0
    tasks: list[SpineTask] = field(default_factory=list)
    projects: list[SpineProject] = field(default_factory=list)
    recent_events: list[SpineEventEnvelope] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    redacted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "room_id": self.room_id,
            "captured_at": self.captured_at,
            "status_counts": dict(self.status_counts),
            "task_count": int(self.task_count),
            "project_count": int(self.project_count),
            "event_count": int(self.event_count),
            "awaiting_approval_count": int(self.awaiting_approval_count),
            "handoff_count": int(self.handoff_count),
            "orphan_task_count": int(self.orphan_task_count),
            "unassigned_open_task_count": int(self.unassigned_open_task_count),
            "tasks": [t.to_dict() for t in self.tasks],
            "projects": [p.to_dict() for p in self.projects],
            "recent_events": [e.to_dict() for e in self.recent_events],
            "metadata": dict(self.metadata),
            "redacted": bool(self.redacted),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SpineDashboardSnapshot":
        tasks_raw = raw.get("tasks") or []
        projects_raw = raw.get("projects") or []
        events_raw = raw.get("recent_events") or []
        tasks = [SpineTask.from_dict(item) for item in tasks_raw if isinstance(item, Mapping)]
        projects = [SpineProject.from_dict(item) for item in projects_raw if isinstance(item, Mapping)]
        events = [SpineEventEnvelope.from_dict(item) for item in events_raw if isinstance(item, Mapping)]
        return cls(
            room_id=_coerce_str(raw.get("room_id")),
            captured_at=str(raw.get("captured_at") or ""),
            status_counts={str(k): int(v) for k, v in (raw.get("status_counts") or {}).items()},
            task_count=int(raw.get("task_count") or 0),
            project_count=int(raw.get("project_count") or 0),
            event_count=int(raw.get("event_count") or 0),
            awaiting_approval_count=int(raw.get("awaiting_approval_count") or 0),
            handoff_count=int(raw.get("handoff_count") or 0),
            orphan_task_count=int(raw.get("orphan_task_count") or 0),
            unassigned_open_task_count=int(raw.get("unassigned_open_task_count") or 0),
            tasks=tasks,
            projects=projects,
            recent_events=events,
            metadata=_coerce_dict(raw.get("metadata")),
            redacted=bool(raw.get("redacted", False)),
        )
