"""Standalone pending approval storage for LIMA Guardian."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from lima_guardian.config import GuardianConfig, get_config

log = logging.getLogger(__name__)

_SECRET_KEY_RE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key|credential|"
    r"auth[_-]?token|passphrase|private[_-]?key|vault[_-]?key)"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_approvals (
  confirm_id TEXT PRIMARY KEY,
  tool_name TEXT NOT NULL,
  tool_args_json TEXT NOT NULL,
  user_id TEXT,
  room_id TEXT,
  status TEXT NOT NULL,
  decision_reason TEXT,
  decided_by TEXT,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  decided_at REAL
);

CREATE INDEX IF NOT EXISTS idx_pending_approvals_room_id ON pending_approvals(room_id);
CREATE INDEX IF NOT EXISTS idx_pending_approvals_user_id ON pending_approvals(user_id);
CREATE INDEX IF NOT EXISTS idx_pending_approvals_status ON pending_approvals(status);
CREATE INDEX IF NOT EXISTS idx_pending_approvals_expires_at ON pending_approvals(expires_at);
"""


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass(frozen=True)
class PendingApproval:
    confirm_id: str
    tool_name: str
    tool_args: dict[str, Any]
    user_id: Optional[str]
    room_id: Optional[str]
    status: ApprovalStatus
    created_at: float
    expires_at: float
    decision_reason: str | None = None
    decided_by: str | None = None
    decided_at: float | None = None

    def is_expired(self, now: float | None = None) -> bool:
        if self.status == ApprovalStatus.EXPIRED:
            return True
        if now is None:
            now = time.time()
        return now >= self.expires_at


def redact_tool_args_for_event(tool_args: Any) -> Any:
    if isinstance(tool_args, dict):
        safe: dict[str, Any] = {}
        for key, value in tool_args.items():
            if _SECRET_KEY_RE.search(str(key)):
                safe[key] = "[REDACTED]"
            else:
                safe[key] = redact_tool_args_for_event(value)
        return safe
    if isinstance(tool_args, list):
        return [redact_tool_args_for_event(item) for item in tool_args]
    return tool_args


def _db_path(cfg: GuardianConfig) -> Path:
    path = cfg.data_dir / "pending_approvals.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _conn(cfg: GuardianConfig) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(cfg))
    conn.row_factory = sqlite3.Row
    return conn


def init_pending_approvals_db(cfg: GuardianConfig | None = None) -> None:
    if cfg is None:
        cfg = get_config()
    with _conn(cfg) as conn:
        conn.executescript(_SCHEMA)


def _decode_tool_args(raw: str) -> dict[str, Any]:
    try:
        tool_args = json.loads(raw or "{}")
        if isinstance(tool_args, dict):
            return tool_args
    except Exception:
        pass
    return {}


def _row_to_pending_approval(row: sqlite3.Row) -> PendingApproval:
    return PendingApproval(
        confirm_id=str(row["confirm_id"]),
        tool_name=str(row["tool_name"]),
        tool_args=_decode_tool_args(str(row["tool_args_json"])),
        user_id=row["user_id"],
        room_id=row["room_id"],
        status=ApprovalStatus(str(row["status"])),
        created_at=float(row["created_at"]),
        expires_at=float(row["expires_at"]),
        decision_reason=row["decision_reason"],
        decided_by=row["decided_by"],
        decided_at=float(row["decided_at"]) if row["decided_at"] is not None else None,
    )


def _emit_approval_event(
    event_type: str,
    approval: PendingApproval,
    cfg: GuardianConfig,
) -> None:
    try:
        if cfg.on_approval_event is not None:
            cfg.on_approval_event(
                event_type,
                approval.confirm_id,
                {
                    "tool_name": approval.tool_name,
                    "user_id": approval.user_id,
                    "room_id": approval.room_id,
                    "status": approval.status.value,
                    "created_at": approval.created_at,
                    "expires_at": approval.expires_at,
                    "decided_at": approval.decided_at,
                    "decided_by": approval.decided_by,
                    "decision_reason": approval.decision_reason,
                    "tool_args": redact_tool_args_for_event(approval.tool_args),
                },
            )
    except Exception:
        log.exception("[pending-approvals] Approval event callback failed")


def expire_pending_approvals(
    *,
    cfg: GuardianConfig | None = None,
    now: float | None = None,
) -> list[PendingApproval]:
    if cfg is None:
        cfg = get_config()
    if now is None:
        now = time.time()
    init_pending_approvals_db(cfg)
    with _conn(cfg) as conn:
        rows = conn.execute(
            """
            SELECT * FROM pending_approvals
            WHERE status = ? AND expires_at <= ?
            """,
            (ApprovalStatus.PENDING.value, now),
        ).fetchall()
        expired = [_row_to_pending_approval(row) for row in rows]
        if expired:
            conn.execute(
                """
                UPDATE pending_approvals
                SET status = ?, decided_at = ?, decision_reason = COALESCE(decision_reason, ?)
                WHERE status = ? AND expires_at <= ?
                """,
                (
                    ApprovalStatus.EXPIRED.value,
                    now,
                    "Pending approval expired.",
                    ApprovalStatus.PENDING.value,
                    now,
                ),
            )
    results: list[PendingApproval] = []
    for approval in expired:
        expired_approval = PendingApproval(
            **{
                **approval.__dict__,
                "status": ApprovalStatus.EXPIRED,
                "decision_reason": approval.decision_reason or "Pending approval expired.",
                "decided_at": now,
            }
        )
        _emit_approval_event("approval.expired", expired_approval, cfg)
        results.append(expired_approval)
    return results


def create_pending_approval(
    *,
    confirm_id: str,
    tool_name: str,
    tool_args: dict[str, Any] | None,
    user_id: str | None,
    room_id: str | None,
    ttl_seconds: int | None = None,
    cfg: GuardianConfig | None = None,
) -> PendingApproval:
    if cfg is None:
        cfg = get_config()
    init_pending_approvals_db(cfg)
    expire_pending_approvals(cfg=cfg)

    now = time.time()
    expires_at = now + max(1, ttl_seconds if ttl_seconds is not None else cfg.pending_approval_ttl)
    payload = json.dumps(tool_args or {}, ensure_ascii=False)
    with _conn(cfg) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO pending_approvals
            (confirm_id, tool_name, tool_args_json, user_id, room_id, status, decision_reason, decided_by, created_at, expires_at, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL)
            """,
            (
                confirm_id,
                tool_name,
                payload,
                user_id,
                room_id,
                ApprovalStatus.PENDING.value,
                now,
                expires_at,
            ),
        )
    approval = PendingApproval(
        confirm_id=confirm_id,
        tool_name=tool_name,
        tool_args=tool_args or {},
        user_id=user_id,
        room_id=room_id,
        status=ApprovalStatus.PENDING,
        created_at=now,
        expires_at=expires_at,
    )
    _emit_approval_event("approval.required", approval, cfg)
    return approval


def get_pending_approval(
    confirm_id: str,
    *,
    cfg: GuardianConfig | None = None,
) -> PendingApproval | None:
    if cfg is None:
        cfg = get_config()
    init_pending_approvals_db(cfg)
    expire_pending_approvals(cfg=cfg)
    with _conn(cfg) as conn:
        row = conn.execute(
            "SELECT * FROM pending_approvals WHERE confirm_id = ?",
            (confirm_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_pending_approval(row)


def _update_approval_status(
    confirm_id: str,
    *,
    new_status: ApprovalStatus,
    decided_by: str | None,
    decision_reason: str | None,
    cfg: GuardianConfig,
) -> PendingApproval | None:
    init_pending_approvals_db(cfg)
    expire_pending_approvals(cfg=cfg)
    current = get_pending_approval(confirm_id, cfg=cfg)
    if current is None or current.status != ApprovalStatus.PENDING:
        return current

    decided_at = time.time()
    with _conn(cfg) as conn:
        conn.execute(
            """
            UPDATE pending_approvals
            SET status = ?, decision_reason = ?, decided_by = ?, decided_at = ?
            WHERE confirm_id = ? AND status = ?
            """,
            (
                new_status.value,
                decision_reason,
                decided_by,
                decided_at,
                confirm_id,
                ApprovalStatus.PENDING.value,
            ),
        )
    updated = PendingApproval(
        **{
            **current.__dict__,
            "status": new_status,
            "decision_reason": decision_reason,
            "decided_by": decided_by,
            "decided_at": decided_at,
        }
    )
    event_type = "approval.approved" if new_status == ApprovalStatus.APPROVED else "approval.denied"
    _emit_approval_event(event_type, updated, cfg)
    return updated


def approve_pending_approval(
    confirm_id: str,
    *,
    decided_by: str | None = None,
    decision_reason: str | None = None,
    cfg: GuardianConfig | None = None,
) -> PendingApproval | None:
    if cfg is None:
        cfg = get_config()
    return _update_approval_status(
        confirm_id,
        new_status=ApprovalStatus.APPROVED,
        decided_by=decided_by,
        decision_reason=decision_reason or "Approved.",
        cfg=cfg,
    )


def deny_pending_approval(
    confirm_id: str,
    *,
    decided_by: str | None = None,
    decision_reason: str | None = None,
    cfg: GuardianConfig | None = None,
) -> PendingApproval | None:
    if cfg is None:
        cfg = get_config()
    return _update_approval_status(
        confirm_id,
        new_status=ApprovalStatus.DENIED,
        decided_by=decided_by,
        decision_reason=decision_reason or "Denied.",
        cfg=cfg,
    )


def list_pending_approvals(
    *,
    room_ids: list[str] | None = None,
    user_id: str | None = None,
    status: ApprovalStatus | None = None,
    limit: int = 25,
    cfg: GuardianConfig | None = None,
) -> list[PendingApproval]:
    if cfg is None:
        cfg = get_config()
    init_pending_approvals_db(cfg)
    expire_pending_approvals(cfg=cfg)

    clauses: list[str] = []
    params: list[Any] = []
    if room_ids:
        placeholders = ", ".join("?" for _ in room_ids)
        clauses.append(f"room_id IN ({placeholders})")
        params.extend(room_ids)
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status.value)

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(max(1, min(limit, 100)))
    with _conn(cfg) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM pending_approvals
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    return [_row_to_pending_approval(row) for row in rows]
