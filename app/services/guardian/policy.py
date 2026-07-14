"""Sparkbot-compatible wrapper around pure Guardian policy core."""

from __future__ import annotations

from typing import Any, Mapping

from guardian_core.policy import (
    PolicyAction,
    PolicyDecision,
    PolicyScope,
    ToolPolicy,
    decide_tool_use as _core_decide_tool_use,
    get_tool_policy as _core_get_tool_policy,
)


def get_tool_policy(tool_name: str, args: dict[str, Any] | None = None) -> ToolPolicy:
    return _core_get_tool_policy(
        tool_name,
        args,
        extra_policies=_load_skill_policies(),
    )


def decide_tool_use(
    tool_name: str,
    args: dict[str, Any] | None = None,
    *,
    room_execution_allowed: bool | None = None,
    is_operator: bool = False,
    is_privileged: bool = False,
) -> PolicyDecision:
    return _core_decide_tool_use(
        tool_name,
        args,
        room_execution_allowed=room_execution_allowed,
        is_operator=is_operator,
        is_privileged=is_privileged,
        extra_policies=_load_skill_policies(),
    )


def _load_skill_policies() -> Mapping[str, Mapping[str, Any]]:
    try:
        from app.services.skills import _registry as skill_registry
    except Exception:
        return {}
    policies = getattr(skill_registry, "policies", {})
    if isinstance(policies, Mapping):
        return policies
    return {}


__all__ = [
    "PolicyAction",
    "PolicyDecision",
    "PolicyScope",
    "ToolPolicy",
    "decide_tool_use",
    "get_tool_policy",
]
