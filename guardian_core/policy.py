"""Pure Guardian policy semantics.

This module intentionally has no dependency on Sparkbot ``app.*`` modules,
databases, routes, skills, vault implementations, background jobs, or tool
execution. It preserves the first policy slice needed by LIMA:
allow, confirm, deny, privileged, and privileged_reveal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping


PolicyAction = Literal["allow", "confirm", "deny", "privileged", "privileged_reveal"]
PolicyScope = Literal["read", "write", "execute", "admin"]


@dataclass(frozen=True)
class ToolPolicy:
    tool_name: str
    scope: PolicyScope
    resource: str
    default_action: PolicyAction
    action_type: str
    high_risk: bool = False
    requires_execution_gate: bool = False


@dataclass(frozen=True)
class PolicyDecision:
    tool_name: str
    scope: PolicyScope
    resource: str
    action: PolicyAction
    action_type: str
    high_risk: bool
    reason: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "tool_name": self.tool_name,
                "scope": self.scope,
                "resource": self.resource,
                "action": self.action,
                "action_type": self.action_type,
                "high_risk": self.high_risk,
                "reason": self.reason,
            }
        )


READ_ONLY_SERVICE_ACTIONS = {
    "status",
    "service_status",
    "show_status",
    "logs",
    "log",
    "service_logs",
    "show_logs",
}


def list_tool_policies() -> dict[str, ToolPolicy]:
    """Return the built-in policy registry."""

    return dict(TOOL_POLICIES)


def get_tool_policy(
    tool_name: str,
    args: Mapping[str, Any] | None = None,
    *,
    extra_policies: Mapping[str, Mapping[str, Any] | ToolPolicy] | None = None,
) -> ToolPolicy:
    """Return a policy for a tool, defaulting unknown tools to deny."""

    args = args or {}
    normalized_tool = _required_tool_name(tool_name)
    if normalized_tool == "server_manage_service":
        action = str(args.get("action", "")).strip().lower()
        if action in READ_ONLY_SERVICE_ACTIONS:
            return ToolPolicy(
                tool_name=normalized_tool,
                scope="read",
                resource="service",
                default_action="allow",
                action_type="read",
                high_risk=False,
            )

    if extra_policies and normalized_tool in extra_policies:
        return _coerce_tool_policy(normalized_tool, extra_policies[normalized_tool])

    return TOOL_POLICIES.get(
        normalized_tool,
        ToolPolicy(
            tool_name=normalized_tool,
            scope="admin",
            resource="unknown",
            default_action="deny",
            action_type="deny",
        ),
    )


def decide_tool_use(
    tool_name: str,
    args: Mapping[str, Any] | None = None,
    *,
    room_execution_allowed: bool | None = None,
    is_operator: bool = False,
    is_privileged: bool = False,
    extra_policies: Mapping[str, Mapping[str, Any] | ToolPolicy] | None = None,
) -> PolicyDecision:
    """Decide policy for one tool without executing anything."""

    policy = get_tool_policy(tool_name, args, extra_policies=extra_policies)

    if policy.tool_name.startswith("vault_") and not is_operator:
        return PolicyDecision(
            tool_name=policy.tool_name,
            scope=policy.scope,
            resource=policy.resource,
            action="deny",
            action_type=policy.action_type,
            high_risk=True,
            reason="Vault tools are restricted to configured operators.",
        )

    if policy.default_action == "deny":
        return PolicyDecision(
            tool_name=policy.tool_name,
            scope=policy.scope,
            resource=policy.resource,
            action="deny",
            action_type=policy.action_type,
            high_risk=policy.high_risk,
            reason=f"Tool '{policy.tool_name}' is not approved by Guardian policy.",
        )

    if policy.requires_execution_gate and not room_execution_allowed:
        return PolicyDecision(
            tool_name=policy.tool_name,
            scope=policy.scope,
            resource=policy.resource,
            action="deny",
            action_type=policy.action_type,
            high_risk=policy.high_risk,
            reason=(
                "Execution is disabled for this room. Enable the room execution gate "
                "before using server or SSH operations."
            ),
        )

    if policy.default_action == "confirm":
        return PolicyDecision(
            tool_name=policy.tool_name,
            scope=policy.scope,
            resource=policy.resource,
            action="confirm",
            action_type=policy.action_type,
            high_risk=policy.high_risk,
            reason=f"{policy.scope.title()} access to {policy.resource} requires confirmation.",
        )

    if policy.default_action == "privileged":
        if is_privileged:
            return PolicyDecision(
                tool_name=policy.tool_name,
                scope=policy.scope,
                resource=policy.resource,
                action="allow",
                action_type=policy.action_type,
                high_risk=policy.high_risk,
                reason=f"Privileged access to {policy.resource} is allowed.",
            )
        return PolicyDecision(
            tool_name=policy.tool_name,
            scope=policy.scope,
            resource=policy.resource,
            action="privileged",
            action_type=policy.action_type,
            high_risk=policy.high_risk,
            reason=f"'{policy.tool_name}' requires break-glass privileged mode.",
        )

    if policy.default_action == "privileged_reveal":
        if is_privileged:
            return PolicyDecision(
                tool_name=policy.tool_name,
                scope=policy.scope,
                resource=policy.resource,
                action="confirm",
                action_type=policy.action_type,
                high_risk=policy.high_risk,
                reason=f"Destructive or reveal operation on {policy.resource} requires confirmation.",
            )
        return PolicyDecision(
            tool_name=policy.tool_name,
            scope=policy.scope,
            resource=policy.resource,
            action="privileged_reveal",
            action_type=policy.action_type,
            high_risk=policy.high_risk,
            reason=f"'{policy.tool_name}' requires break-glass privileged mode.",
        )

    return PolicyDecision(
        tool_name=policy.tool_name,
        scope=policy.scope,
        resource=policy.resource,
        action="allow",
        action_type=policy.action_type,
        high_risk=policy.high_risk,
        reason=f"{policy.scope.title()} access to {policy.resource} is allowed.",
    )


def _build_policy_registry() -> dict[str, ToolPolicy]:
    registry: dict[str, ToolPolicy] = {}

    def add(
        tool_name: str,
        *,
        scope: PolicyScope,
        resource: str,
        default_action: PolicyAction,
        action_type: str,
        high_risk: bool = False,
        requires_execution_gate: bool = False,
    ) -> None:
        registry[tool_name] = ToolPolicy(
            tool_name=tool_name,
            scope=scope,
            resource=resource,
            default_action=default_action,
            action_type=action_type,
            high_risk=high_risk,
            requires_execution_gate=requires_execution_gate,
        )

    for tool_name in (
        "web_search",
        "get_datetime",
        "calculate",
        "list_tasks",
        "github_list_prs",
        "github_get_pr",
        "github_get_ci_status",
        "slack_list_channels",
        "slack_get_channel_history",
        "notion_search",
        "notion_get_page",
        "confluence_search",
        "confluence_get_page",
        "gmail_fetch_inbox",
        "gmail_search",
        "gmail_get_message",
        "drive_search",
        "drive_get_file",
        "email_fetch_inbox",
        "email_search",
        "list_reminders",
        "calendar_list_events",
        "guardian_list_tasks",
        "guardian_list_runs",
    ):
        add(tool_name, scope="read", resource="workspace", default_action="allow", action_type="read")

    for tool_name, resource in (
        ("remember_fact", "memory"),
        ("forget_fact", "memory"),
        ("create_task", "room_task"),
        ("complete_task", "room_task"),
        ("set_reminder", "reminder"),
        ("cancel_reminder", "reminder"),
        ("guardian_run_task", "guardian_task"),
        ("guardian_pause_task", "guardian_task"),
    ):
        add(tool_name, scope="write", resource=resource, default_action="allow", action_type="room_write")

    for tool_name, resource in (
        ("gmail_send", "gmail"),
        ("email_send", "email"),
        ("slack_send_message", "slack"),
        ("github_create_issue", "github"),
        ("notion_create_page", "notion"),
        ("confluence_create_page", "confluence"),
        ("calendar_create_event", "calendar"),
        ("drive_create_folder", "drive"),
        ("guardian_schedule_task", "guardian_task"),
    ):
        add(
            tool_name,
            scope="write",
            resource=resource,
            default_action="confirm",
            action_type="write_external",
            high_risk=True,
        )

    add(
        "server_read_command",
        scope="execute",
        resource="server",
        default_action="allow",
        action_type="command_exec",
        high_risk=True,
        requires_execution_gate=True,
    )
    add(
        "ssh_read_command",
        scope="execute",
        resource="ssh",
        default_action="allow",
        action_type="ssh_exec",
        high_risk=True,
        requires_execution_gate=True,
    )
    add(
        "server_manage_service",
        scope="execute",
        resource="service",
        default_action="confirm",
        action_type="service_control",
        high_risk=True,
        requires_execution_gate=True,
    )

    add("vault_list_secrets", scope="read", resource="vault", default_action="allow", action_type="read")
    add("vault_use_secret", scope="read", resource="vault", default_action="allow", action_type="read")
    add(
        "vault_add_secret",
        scope="write",
        resource="vault",
        default_action="privileged",
        action_type="vault_write",
        high_risk=True,
    )
    add(
        "vault_update_secret",
        scope="write",
        resource="vault",
        default_action="privileged",
        action_type="vault_write",
        high_risk=True,
    )
    add(
        "vault_reveal_secret",
        scope="read",
        resource="vault",
        default_action="privileged_reveal",
        action_type="vault_reveal",
        high_risk=True,
    )
    add(
        "vault_delete_secret",
        scope="write",
        resource="vault",
        default_action="privileged_reveal",
        action_type="vault_reveal",
        high_risk=True,
    )

    return registry


def _coerce_tool_policy(tool_name: str, value: Mapping[str, Any] | ToolPolicy) -> ToolPolicy:
    if isinstance(value, ToolPolicy):
        return value
    return ToolPolicy(tool_name=tool_name, **dict(value))


def _required_tool_name(tool_name: str) -> str:
    if not isinstance(tool_name, str) or not tool_name.strip():
        return ""
    return tool_name.strip()


TOOL_POLICIES = _build_policy_registry()


__all__ = [
    "PolicyAction",
    "PolicyDecision",
    "PolicyScope",
    "READ_ONLY_SERVICE_ACTIONS",
    "TOOL_POLICIES",
    "ToolPolicy",
    "decide_tool_use",
    "get_tool_policy",
    "list_tool_policies",
]
