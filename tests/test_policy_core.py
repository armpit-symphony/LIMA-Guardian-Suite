"""Tests for the pure Guardian policy-core slice."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
import sys

from guardian_core.policy import decide_tool_use, get_tool_policy


def test_policy_core_import_does_not_require_sparkbot_app_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)

    module = importlib.import_module("guardian_core.policy")

    assert module.decide_tool_use("get_datetime").action == "allow"
    assert "app" not in sys.modules
    assert not any(module_name.startswith("app.") for module_name in sys.modules)


def test_policy_core_source_has_no_app_imports() -> None:
    tree = ast.parse(Path("guardian_core/policy.py").read_text(encoding="utf-8"))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders.extend(
                alias.name
                for alias in node.names
                if alias.name == "app" or alias.name.startswith("app.")
            )
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "app" or module.startswith("app."):
                offenders.append(module)

    assert offenders == []


def test_read_tool_returns_allow() -> None:
    decision = decide_tool_use("get_datetime")

    assert decision.action == "allow"
    assert decision.scope == "read"
    assert decision.action_type == "read"


def test_external_write_returns_confirm() -> None:
    decision = decide_tool_use("gmail_send")

    assert decision.action == "confirm"
    assert decision.scope == "write"
    assert decision.action_type == "write_external"
    assert decision.high_risk is True


def test_unknown_tool_returns_deny() -> None:
    decision = decide_tool_use("unknown_tool")

    assert decision.action == "deny"
    assert decision.scope == "admin"
    assert decision.resource == "unknown"


def test_execution_gated_tool_denies_without_execution_gate() -> None:
    decision = decide_tool_use("server_read_command", room_execution_allowed=False)

    assert decision.action == "deny"
    assert decision.scope == "execute"
    assert "Execution is disabled" in decision.reason


def test_execution_gated_read_command_allows_only_with_execution_gate() -> None:
    without_gate = decide_tool_use("server_read_command", room_execution_allowed=False)
    with_gate = decide_tool_use("server_read_command", room_execution_allowed=True)

    assert without_gate.action == "deny"
    assert with_gate.action == "allow"
    assert with_gate.action_type == "command_exec"


def test_read_only_service_command_keeps_existing_allow_semantics() -> None:
    policy = get_tool_policy("server_manage_service", {"action": "status"})
    decision = decide_tool_use("server_manage_service", {"action": "status"})

    assert policy.scope == "read"
    assert policy.default_action == "allow"
    assert decision.action == "allow"


def test_vault_paths_require_operator_or_privileged_state() -> None:
    assert decide_tool_use("vault_add_secret").action == "deny"
    assert decide_tool_use("vault_update_secret").action == "deny"
    assert decide_tool_use("vault_delete_secret").action == "deny"
    assert decide_tool_use("vault_reveal_secret").action == "deny"

    assert decide_tool_use("vault_add_secret", is_operator=True).action == "privileged"
    assert decide_tool_use("vault_update_secret", is_operator=True).action == "privileged"
    assert decide_tool_use("vault_delete_secret", is_operator=True).action == "privileged_reveal"
    assert decide_tool_use("vault_reveal_secret", is_operator=True).action == "privileged_reveal"

    assert decide_tool_use("vault_add_secret", is_operator=True, is_privileged=True).action == "allow"
    assert decide_tool_use("vault_update_secret", is_operator=True, is_privileged=True).action == "allow"
    assert decide_tool_use("vault_delete_secret", is_operator=True, is_privileged=True).action == "confirm"
    assert decide_tool_use("vault_reveal_secret", is_operator=True, is_privileged=True).action == "confirm"
