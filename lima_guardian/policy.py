"""Standalone policy engine core for LIMA Guardian.

The core stays product-generic: callers inject tool policies and decide how to
map product-specific tool names to those policies.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping


class PolicyDecisionAction(str, Enum):
    ALLOW = "allow"
    REVIEW = "review"
    DENY = "deny"


class PolicyScope(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ToolPolicy:
    tool_name: str
    scope: PolicyScope
    resource: str
    default_decision: PolicyDecisionAction
    action_type: str
    risk_level: RiskLevel = RiskLevel.LOW
    requires_privileged: bool = False
    requires_execution_gate: bool = False
    enabled: bool = True
    notes: str = ""


@dataclass(frozen=True)
class PolicyDecision:
    tool_name: str
    scope: PolicyScope
    resource: str
    action: PolicyDecisionAction
    action_type: str
    risk_level: RiskLevel
    reason: str
    requires_privileged: bool = False
    requires_execution_gate: bool = False

    @property
    def high_risk(self) -> bool:
        return self.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}

    def to_json(self) -> str:
        return json.dumps(
            {
                "tool_name": self.tool_name,
                "scope": self.scope.value,
                "resource": self.resource,
                "action": self.action.value,
                "action_type": self.action_type,
                "risk_level": self.risk_level.value,
                "reason": self.reason,
                "requires_privileged": self.requires_privileged,
                "requires_execution_gate": self.requires_execution_gate,
            }
        )


PolicyRegistry = dict[str, ToolPolicy]


def build_policy_registry(policies: Iterable[ToolPolicy]) -> PolicyRegistry:
    return {policy.tool_name: policy for policy in policies}


def unknown_tool_policy(tool_name: str) -> ToolPolicy:
    return ToolPolicy(
        tool_name=tool_name,
        scope=PolicyScope.ADMIN,
        resource="unknown",
        default_decision=PolicyDecisionAction.DENY,
        action_type="deny",
        risk_level=RiskLevel.CRITICAL,
        enabled=False,
        notes="Unknown tools are denied until an adapter injects an explicit policy.",
    )


def classify_tool_use(
    tool_name: str,
    registry: Mapping[str, ToolPolicy] | None = None,
) -> ToolPolicy:
    if registry is None:
        registry = {}
    return registry.get(tool_name, unknown_tool_policy(tool_name))


def decide_tool_use(
    tool_name: str,
    args: dict[str, Any] | None = None,
    *,
    registry: Mapping[str, ToolPolicy] | None = None,
    execution_allowed: bool | None = None,
    is_privileged: bool = False,
) -> PolicyDecision:
    del args  # reserved for adapters that may classify based on arguments
    policy = classify_tool_use(tool_name, registry)

    if not policy.enabled or policy.default_decision == PolicyDecisionAction.DENY:
        reason = policy.notes or f"Tool '{tool_name}' is not approved by policy."
        return PolicyDecision(
            tool_name=tool_name,
            scope=policy.scope,
            resource=policy.resource,
            action=PolicyDecisionAction.DENY,
            action_type=policy.action_type,
            risk_level=policy.risk_level,
            reason=reason,
            requires_privileged=policy.requires_privileged,
            requires_execution_gate=policy.requires_execution_gate,
        )

    if policy.requires_execution_gate and not execution_allowed:
        return PolicyDecision(
            tool_name=tool_name,
            scope=policy.scope,
            resource=policy.resource,
            action=PolicyDecisionAction.DENY,
            action_type=policy.action_type,
            risk_level=policy.risk_level,
            reason=f"{policy.scope.value.title()} access to {policy.resource} requires an execution gate.",
            requires_privileged=policy.requires_privileged,
            requires_execution_gate=True,
        )

    if policy.requires_privileged and not is_privileged:
        return PolicyDecision(
            tool_name=tool_name,
            scope=policy.scope,
            resource=policy.resource,
            action=PolicyDecisionAction.REVIEW,
            action_type=policy.action_type,
            risk_level=policy.risk_level,
            reason=f"{policy.scope.value.title()} access to {policy.resource} requires privileged review.",
            requires_privileged=True,
            requires_execution_gate=policy.requires_execution_gate,
        )

    if policy.default_decision == PolicyDecisionAction.REVIEW:
        return PolicyDecision(
            tool_name=tool_name,
            scope=policy.scope,
            resource=policy.resource,
            action=PolicyDecisionAction.REVIEW,
            action_type=policy.action_type,
            risk_level=policy.risk_level,
            reason=f"{policy.scope.value.title()} access to {policy.resource} requires review.",
            requires_privileged=policy.requires_privileged,
            requires_execution_gate=policy.requires_execution_gate,
        )

    return PolicyDecision(
        tool_name=tool_name,
        scope=policy.scope,
        resource=policy.resource,
        action=PolicyDecisionAction.ALLOW,
        action_type=policy.action_type,
        risk_level=policy.risk_level,
        reason=f"{policy.scope.value.title()} access to {policy.resource} is allowed.",
        requires_privileged=policy.requires_privileged,
        requires_execution_gate=policy.requires_execution_gate,
    )
