"""Tests for the standalone Guardian decision contract."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from guardian_core import (
    GuardianDecision,
    GuardianEvaluationRequest,
    evaluate_guardian_request,
)
from guardian_core.policy import PolicyDecision


def _request(action: str, **overrides: object) -> GuardianEvaluationRequest:
    values: dict[str, object] = {
        "requested_action": action,
        "arguments": {},
        "policy_context": {},
        "actor_id": "operator-local",
        "task_ref": "task://guardian/test",
        "source": "guardian-core-tests",
        "metadata": {"test": True},
    }
    values.update(overrides)
    return GuardianEvaluationRequest(**values)  # type: ignore[arg-type]


def test_public_imports_are_available() -> None:
    assert GuardianEvaluationRequest.__module__ == "guardian_core.decision"
    assert GuardianDecision.__module__ == "guardian_core.decision"
    assert evaluate_guardian_request.__module__ == "guardian_core.decision"


def test_allow_mapping_has_guardian_owned_identity_and_no_execution() -> None:
    decision = evaluate_guardian_request(_request("get_datetime"))

    assert decision.decision_id.startswith("guardian-decision:")
    assert decision.status == "allow"
    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.metadata["execution_performed"] is False
    assert decision.metadata["external_services_called"] is False


def test_deny_mapping_fails_closed() -> None:
    decision = evaluate_guardian_request(_request("unknown_tool"))

    assert decision.decision_id
    assert decision.status == "deny"
    assert decision.allowed is False
    assert decision.requires_approval is False


def test_confirmation_mapping_requires_approval() -> None:
    decision = evaluate_guardian_request(_request("gmail_send"))

    assert decision.status == "requires_approval"
    assert decision.allowed is False
    assert decision.requires_approval is True


def test_caller_policy_context_cannot_self_assert_execution_authority() -> None:
    decision = evaluate_guardian_request(
        _request(
            "server_read_command",
            policy_context={
                "room_execution_allowed": True,
                "is_operator": True,
                "is_privileged": True,
            },
        )
    )

    assert decision.status == "deny"
    assert decision.allowed is False


def test_normal_evaluations_produce_unique_decision_ids() -> None:
    first = evaluate_guardian_request(_request("get_datetime"))
    second = evaluate_guardian_request(_request("get_datetime"))

    assert first.decision_id != second.decision_id


def test_internal_factories_are_patchable_for_deterministic_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "guardian_core.decision._new_decision_id",
        lambda: "guardian-decision:fixed",
    )
    monkeypatch.setattr(
        "guardian_core.decision._utc_now",
        lambda: "2026-07-13T00:00:00Z",
    )

    decision = evaluate_guardian_request(_request("get_datetime"))

    assert decision.decision_id == "guardian-decision:fixed"
    assert decision.created_at == "2026-07-13T00:00:00Z"


def test_malformed_policy_output_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "guardian_core.decision._evaluate_policy",
        lambda _request: object(),
    )

    decision = evaluate_guardian_request(_request("get_datetime"))

    assert decision.status == "deny"
    assert decision.allowed is False
    assert "invalid result" in decision.reason


def test_unknown_policy_action_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    malformed = PolicyDecision(
        tool_name="get_datetime",
        scope="read",
        resource="workspace",
        action="unexpected",  # type: ignore[arg-type]
        action_type="read",
        high_risk=False,
        reason="malformed test result",
    )
    monkeypatch.setattr(
        "guardian_core.decision._evaluate_policy",
        lambda _request: malformed,
    )

    decision = evaluate_guardian_request(_request("get_datetime"))

    assert decision.status == "deny"
    assert decision.allowed is False
    assert "unknown" in decision.reason


def test_decision_serializes_to_dictionary_and_json() -> None:
    decision = evaluate_guardian_request(
        _request(
            "get_datetime",
            arguments={"nested": ["value"]},
            policy_context={"network_scope": "loopback_only"},
        )
    )

    payload = decision.to_dict()
    encoded = decision.to_json()

    assert json.loads(encoded) == payload
    assert payload["decision_id"] == decision.decision_id
    assert payload["metadata"]["policy"]["action"] == "allow"


def test_request_mappings_are_defensively_normalized() -> None:
    arguments = {"nested": ["before"]}
    request = _request("get_datetime", arguments=arguments)
    arguments["nested"].append("after")

    assert request.arguments["nested"] == ("before",)
    with pytest.raises(TypeError):
        request.arguments["new"] = "value"  # type: ignore[index]


def test_decision_contract_has_no_consumer_or_sparkbot_imports() -> None:
    source_path = Path("guardian_core/decision.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    forbidden_prefixes = (
        "app",
        "arc_bot_shell",
        "lima",
        "sparkbot",
    )
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders.extend(
                alias.name
                for alias in node.names
                if alias.name.startswith(forbidden_prefixes)
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(forbidden_prefixes):
                offenders.append(module)

    assert offenders == []


def test_arc_local_preview_consumer_proof_shape() -> None:
    request = GuardianEvaluationRequest(
        requested_action="arc.local_model_preview",
        arguments={},
        policy_context={"network_scope": "loopback_only"},
    )

    decision = evaluate_guardian_request(request)

    assert decision.decision_id
    assert decision.status in {"allow", "deny", "requires_approval"}
