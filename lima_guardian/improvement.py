"""Standalone feedback and correction store for LIMA Guardian."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lima_guardian.config import GuardianConfig, get_config


@dataclass(frozen=True)
class ImprovementEvent:
    event_id: str
    event_type: str
    label: str
    source_text: str
    corrected_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_path(cfg: GuardianConfig) -> Path:
    path = Path(cfg.improvement_store_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_store(cfg: GuardianConfig) -> dict[str, Any]:
    path = _store_path(cfg)
    if not path.exists():
        return {"events": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"events": []}
    if not isinstance(payload, dict):
        return {"events": []}
    events = payload.get("events")
    if not isinstance(events, list):
        payload["events"] = []
    return payload


def _save_store(cfg: GuardianConfig, store: dict[str, Any]) -> None:
    path = _store_path(cfg)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def record_feedback(
    *,
    event_type: str,
    label: str,
    source_text: str,
    corrected_text: str = "",
    metadata: dict[str, Any] | None = None,
    cfg: GuardianConfig | None = None,
) -> ImprovementEvent:
    if cfg is None:
        cfg = get_config()
    event = ImprovementEvent(
        event_id=f"improve-{uuid.uuid4().hex[:12]}",
        event_type=str(event_type).strip() or "feedback",
        label=str(label).strip() or "general",
        source_text=" ".join((source_text or "").split())[:2000],
        corrected_text=" ".join((corrected_text or "").split())[:2000],
        metadata=dict(metadata or {}),
        created_at=_utc_now_iso(),
    )
    store = _load_store(cfg)
    events = store.setdefault("events", [])
    events.insert(0, asdict(event))
    _save_store(cfg, store)
    return event


def list_feedback(
    *,
    event_type: str | None = None,
    label: str | None = None,
    limit: int = 25,
    cfg: GuardianConfig | None = None,
) -> list[ImprovementEvent]:
    if cfg is None:
        cfg = get_config()
    store = _load_store(cfg)
    rows: list[ImprovementEvent] = []
    for item in store.get("events", []):
        if not isinstance(item, dict):
            continue
        if event_type and str(item.get("event_type") or "") != event_type:
            continue
        if label and str(item.get("label") or "") != label:
            continue
        rows.append(ImprovementEvent(**item))
        if len(rows) >= max(1, min(limit, 100)):
            break
    return rows


def summarize_feedback(*, cfg: GuardianConfig | None = None) -> dict[str, Any]:
    if cfg is None:
        cfg = get_config()
    store = _load_store(cfg)
    total_events = 0
    by_type: dict[str, int] = {}
    by_label: dict[str, int] = {}
    corrections = 0
    for item in store.get("events", []):
        if not isinstance(item, dict):
            continue
        total_events += 1
        event_type = str(item.get("event_type") or "feedback")
        label = str(item.get("label") or "general")
        by_type[event_type] = by_type.get(event_type, 0) + 1
        by_label[label] = by_label.get(label, 0) + 1
        if str(item.get("corrected_text") or "").strip():
            corrections += 1
    return {
        "total_events": total_events,
        "corrections_recorded": corrections,
        "event_types": by_type,
        "labels": by_label,
    }
