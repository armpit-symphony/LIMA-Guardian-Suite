from __future__ import annotations

import importlib
from pathlib import Path

from lima_guardian.config import GuardianConfig
from lima_guardian.pending_approvals import (
    ApprovalStatus,
    approve_pending_approval,
    create_pending_approval,
    deny_pending_approval,
    expire_pending_approvals,
    get_pending_approval,
)
from lima_guardian.policy import (
    PolicyDecisionAction,
    PolicyScope,
    RiskLevel,
    ToolPolicy,
    build_policy_registry,
    decide_tool_use,
)


def test_safe_action_allowed():
    registry = build_policy_registry(
        [
            ToolPolicy(
                tool_name="safe_read",
                scope=PolicyScope.READ,
                resource="workspace",
                default_decision=PolicyDecisionAction.ALLOW,
                action_type="read",
                risk_level=RiskLevel.LOW,
            )
        ]
    )

    decision = decide_tool_use("safe_read", registry=registry)

    assert decision.action == PolicyDecisionAction.ALLOW
    assert decision.risk_level == RiskLevel.LOW


def test_risky_action_requires_review():
    registry = build_policy_registry(
        [
            ToolPolicy(
                tool_name="dangerous_write",
                scope=PolicyScope.WRITE,
                resource="deployments",
                default_decision=PolicyDecisionAction.REVIEW,
                action_type="write_external",
                risk_level=RiskLevel.HIGH,
            )
        ]
    )

    decision = decide_tool_use("dangerous_write", registry=registry)

    assert decision.action == PolicyDecisionAction.REVIEW
    assert decision.high_risk is True


def test_blocked_action_denied():
    registry = build_policy_registry(
        [
            ToolPolicy(
                tool_name="blocked_delete",
                scope=PolicyScope.ADMIN,
                resource="production",
                default_decision=PolicyDecisionAction.DENY,
                action_type="deny",
                risk_level=RiskLevel.CRITICAL,
                notes="Destructive production actions are denied in the core policy.",
            )
        ]
    )

    decision = decide_tool_use("blocked_delete", registry=registry)

    assert decision.action == PolicyDecisionAction.DENY
    assert "denied" in decision.reason.lower()


def test_approval_creation_records_pending_state(tmp_path):
    events: list[tuple[str, str, dict]] = []
    cfg = GuardianConfig(
        env_prefix="TEST_LIMA",
        data_dir=tmp_path,
        on_approval_event=lambda event_type, confirm_id, payload: events.append(
            (event_type, confirm_id, payload)
        ),
    )

    approval = create_pending_approval(
        confirm_id="confirm-1",
        tool_name="dangerous_write",
        tool_args={"path": "/tmp/report.txt"},
        user_id="user-1",
        room_id="room-1",
        cfg=cfg,
    )

    stored = get_pending_approval("confirm-1", cfg=cfg)

    assert approval.status == ApprovalStatus.PENDING
    assert stored is not None
    assert stored.tool_args == {"path": "/tmp/report.txt"}
    assert events[0][0] == "approval.required"
    assert events[0][2]["status"] == ApprovalStatus.PENDING.value


def test_approval_approve_flow_preserves_original_args(tmp_path):
    cfg = GuardianConfig(env_prefix="TEST_LIMA", data_dir=tmp_path)
    tool_args = {"path": "/tmp/out.txt", "token": "raw-secret-token"}

    create_pending_approval(
        confirm_id="confirm-2",
        tool_name="dangerous_write",
        tool_args=tool_args,
        user_id="user-2",
        room_id="room-2",
        cfg=cfg,
    )
    approved = approve_pending_approval(
        "confirm-2",
        decided_by="operator-1",
        decision_reason="Looks safe.",
        cfg=cfg,
    )

    assert approved is not None
    assert approved.status == ApprovalStatus.APPROVED
    assert approved.tool_args == tool_args
    assert get_pending_approval("confirm-2", cfg=cfg).tool_args == tool_args


def test_approval_deny_flow(tmp_path):
    cfg = GuardianConfig(env_prefix="TEST_LIMA", data_dir=tmp_path)

    create_pending_approval(
        confirm_id="confirm-3",
        tool_name="dangerous_write",
        tool_args={"path": "/tmp/out.txt"},
        user_id="user-3",
        room_id="room-3",
        cfg=cfg,
    )
    denied = deny_pending_approval(
        "confirm-3",
        decided_by="operator-2",
        decision_reason="Missing justification.",
        cfg=cfg,
    )

    assert denied is not None
    assert denied.status == ApprovalStatus.DENIED
    assert denied.decision_reason == "Missing justification."


def test_approval_ttl_expiry(tmp_path):
    cfg = GuardianConfig(env_prefix="TEST_LIMA", data_dir=tmp_path)

    create_pending_approval(
        confirm_id="confirm-4",
        tool_name="dangerous_write",
        tool_args={"path": "/tmp/out.txt"},
        user_id="user-4",
        room_id="room-4",
        ttl_seconds=1,
        cfg=cfg,
    )
    expired = expire_pending_approvals(cfg=cfg, now=10_000_000_000.0)

    stored = get_pending_approval("confirm-4", cfg=cfg)
    assert len(expired) == 1
    assert expired[0].status == ApprovalStatus.EXPIRED
    assert stored is not None
    assert stored.status == ApprovalStatus.EXPIRED


def test_secret_like_args_are_redacted_in_events_only(tmp_path):
    events: list[tuple[str, str, dict]] = []
    cfg = GuardianConfig(
        env_prefix="TEST_LIMA",
        data_dir=tmp_path,
        on_approval_event=lambda event_type, confirm_id, payload: events.append(
            (event_type, confirm_id, payload)
        ),
    )
    tool_args = {
        "path": "/tmp/out.txt",
        "api_key": "top-secret",
        "nested": {"password": "abc123", "note": "keep"},
    }

    create_pending_approval(
        confirm_id="confirm-5",
        tool_name="dangerous_write",
        tool_args=tool_args,
        user_id="user-5",
        room_id="room-5",
        cfg=cfg,
    )

    emitted = events[0][2]["tool_args"]
    stored = get_pending_approval("confirm-5", cfg=cfg)

    assert emitted["api_key"] == "[REDACTED]"
    assert emitted["nested"]["password"] == "[REDACTED]"
    assert emitted["nested"]["note"] == "keep"
    assert stored is not None
    assert stored.tool_args == tool_args


def test_standalone_modules_do_not_import_sparkbot_or_app():
    policy_module = importlib.import_module("lima_guardian.policy")
    approvals_module = importlib.import_module("lima_guardian.pending_approvals")

    policy_source = Path(policy_module.__file__).read_text(encoding="utf-8")
    approvals_source = Path(approvals_module.__file__).read_text(encoding="utf-8")

    assert "from app" not in policy_source
    assert "import app" not in policy_source
    assert "from app" not in approvals_source
    assert "import app" not in approvals_source
