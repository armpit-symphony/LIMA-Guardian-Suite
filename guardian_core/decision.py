"""Standalone Guardian decision contract built on the pure policy core."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Mapping
import uuid

from .policy import (
    LOCAL_MODEL_PREVIEW_ACTION,
    PolicyDecision,
    decide_local_model_preview,
    decide_tool_use,
)

GUARDIAN_DECISION_STATUSES = ("allow", "deny", "requires_approval")
_APPROVAL_POLICY_ACTIONS = frozenset({"confirm", "privileged", "privileged_reveal"})
_JSON_PRIMITIVES = (str, int, float, bool, type(None))


class FrozenJSONDict(dict[str, Any]):
    """JSON-serializable dictionary that cannot be changed after construction."""

    def _immutable(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("Guardian contract mappings are immutable")

    __delitem__ = _immutable
    __ior__ = _immutable
    __setitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return FrozenJSONDict(
            {str(key): _freeze_json(nested) for key, nested in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, _JSON_PRIMITIVES):
        return value
    raise TypeError(
        f"Guardian contract value is not JSON-serializable: {type(value).__name__}"
    )


def _freeze_mapping(value: Mapping[str, Any], field_name: str) -> FrozenJSONDict:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return _freeze_json(value)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


@dataclass(frozen=True)
class GuardianEvaluationRequest:
    """Package-owned request for a non-executing Guardian policy evaluation."""

    requested_action: str
    arguments: Mapping[str, Any]
    policy_context: Mapping[str, Any]
    actor_id: str | None = None
    task_ref: str | None = None
    source: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.requested_action, str):
            raise TypeError("requested_action must be a string")
        object.__setattr__(self, "requested_action", self.requested_action.strip())
        object.__setattr__(
            self, "arguments", _freeze_mapping(self.arguments, "arguments")
        )
        object.__setattr__(
            self,
            "policy_context",
            _freeze_mapping(self.policy_context, "policy_context"),
        )
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))
        for field_name in ("actor_id", "task_ref", "source"):
            value = getattr(self, field_name)
            if value is not None:
                if not isinstance(value, str):
                    raise TypeError(f"{field_name} must be a string or None")
                object.__setattr__(self, field_name, value.strip() or None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_action": self.requested_action,
            "arguments": _json_ready(self.arguments),
            "policy_context": _json_ready(self.policy_context),
            "actor_id": self.actor_id,
            "task_ref": self.task_ref,
            "source": self.source,
            "metadata": _json_ready(self.metadata),
        }


@dataclass(frozen=True)
class GuardianDecision:
    """Guardian-owned decision identity and normalized policy outcome."""

    decision_id: str
    status: str
    allowed: bool
    requires_approval: bool
    reason: str
    requested_action: str
    risk_level: str | None
    policy_name: str | None
    created_at: str
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, str) or not self.decision_id.strip():
            raise ValueError("decision_id is required")
        if self.status not in GUARDIAN_DECISION_STATUSES:
            raise ValueError("status is not supported")
        if self.status == "allow" and (
            self.allowed is not True or self.requires_approval is not False
        ):
            raise ValueError("allow status requires allowed=True")
        if self.status == "deny" and (
            self.allowed is not False or self.requires_approval is not False
        ):
            raise ValueError("deny status requires allowed=False")
        if self.status == "requires_approval" and (
            self.allowed is not False or self.requires_approval is not True
        ):
            raise ValueError("requires_approval status is inconsistent")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "status": self.status,
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "requested_action": self.requested_action,
            "risk_level": self.risk_level,
            "policy_name": self.policy_name,
            "created_at": self.created_at,
            "metadata": _json_ready(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


def _new_decision_id() -> str:
    return f"guardian-decision:{uuid.uuid4()}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _evaluate_policy(request: GuardianEvaluationRequest) -> PolicyDecision:
    if request.requested_action == LOCAL_MODEL_PREVIEW_ACTION:
        return decide_local_model_preview(request.arguments, request.policy_context)
    return decide_tool_use(request.requested_action, request.arguments)


def _decision_metadata(
    request: GuardianEvaluationRequest,
    policy: PolicyDecision | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "actor_id": request.actor_id,
        "task_ref": request.task_ref,
        "source": request.source,
        "request_metadata": request.metadata,
        "execution_performed": False,
        "external_services_called": False,
    }
    if policy is not None:
        metadata["policy"] = {
            "action": policy.action,
            "scope": policy.scope,
            "resource": policy.resource,
            "action_type": policy.action_type,
            "high_risk": policy.high_risk,
        }
    return metadata


def _fail_closed(
    request: GuardianEvaluationRequest,
    reason: str,
) -> GuardianDecision:
    return GuardianDecision(
        decision_id=_new_decision_id(),
        status="deny",
        allowed=False,
        requires_approval=False,
        reason=reason,
        requested_action=request.requested_action,
        risk_level="blocked",
        policy_name="guardian_core.policy",
        created_at=_utc_now(),
        metadata=_decision_metadata(request, None),
    )


def evaluate_guardian_request(
    request: GuardianEvaluationRequest,
) -> GuardianDecision:
    """Evaluate policy and return a Guardian-owned decision without execution."""

    if not isinstance(request, GuardianEvaluationRequest):
        raise TypeError("request must be a GuardianEvaluationRequest")

    try:
        policy = _evaluate_policy(request)
    except Exception:
        return _fail_closed(
            request, "Guardian policy evaluation failed; denied by default."
        )

    if not isinstance(policy, PolicyDecision):
        return _fail_closed(
            request, "Guardian policy returned an invalid result; denied by default."
        )

    if policy.action == "allow":
        status = "allow"
        allowed = True
        requires_approval = False
    elif policy.action == "deny":
        status = "deny"
        allowed = False
        requires_approval = False
    elif policy.action in _APPROVAL_POLICY_ACTIONS:
        status = "requires_approval"
        allowed = False
        requires_approval = True
    else:
        return _fail_closed(
            request, "Guardian policy action is unknown; denied by default."
        )

    return GuardianDecision(
        decision_id=_new_decision_id(),
        status=status,
        allowed=allowed,
        requires_approval=requires_approval,
        reason=policy.reason,
        requested_action=request.requested_action,
        risk_level="high" if policy.high_risk else "low",
        policy_name="guardian_core.policy",
        created_at=_utc_now(),
        metadata=_decision_metadata(request, policy),
    )


__all__ = [
    "GUARDIAN_DECISION_STATUSES",
    "GuardianDecision",
    "GuardianEvaluationRequest",
    "evaluate_guardian_request",
]
