"""Policy tests for the bounded Arc local model preview request."""

from __future__ import annotations

import socket
from typing import Any

import pytest

from guardian_core import GuardianEvaluationRequest, evaluate_guardian_request

VALID_ARGUMENTS = {
    "model_adapter": "ollama",
    "endpoint": "http://127.0.0.1:11434",
}
VALID_CONTEXT = {
    "network_scope": "loopback_only",
    "external_side_effects": False,
    "credentials_required": False,
    "execution_scope": "model_preview_only",
    "runtime_route": "lima",
}


def _evaluate(
    *,
    action: str = "arc.local_model_preview",
    arguments: dict[str, Any] | None = None,
    policy_context: dict[str, Any] | None = None,
):
    return evaluate_guardian_request(
        GuardianEvaluationRequest(
            requested_action=action,
            arguments=VALID_ARGUMENTS if arguments is None else arguments,
            policy_context=VALID_CONTEXT if policy_context is None else policy_context,
        )
    )


def test_valid_bounded_local_preview_is_allowed_without_execution() -> None:
    decision = _evaluate()

    assert decision.decision_id.startswith("guardian-decision:")
    assert decision.status == "allow"
    assert decision.allowed is True
    assert decision.requires_approval is False
    assert "Bounded Arc local model preview" in decision.reason
    assert decision.metadata["execution_performed"] is False
    assert decision.metadata["external_services_called"] is False


def test_localhost_is_an_approved_loopback_host() -> None:
    decision = _evaluate(
        arguments={**VALID_ARGUMENTS, "endpoint": "http://localhost:11434"}
    )

    assert decision.status == "allow"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://0.0.0.0:11434",
        "http://192.168.1.20:11434",
        "http://203.0.113.10:11434",
        "http://ollama.example.com:11434",
        "http://user:password@127.0.0.1:11434",
        "https://127.0.0.1:11434",
        "ftp://127.0.0.1:11434",
        "http://127.0.0.1:99999",
        "http://[127.0.0.1:11434",
        "http://127.0.0.1:11434/api/generate",
        "http://127.0.0.1\t:11434",
        "",
    ],
)
def test_unapproved_or_malformed_endpoint_is_denied(endpoint: str) -> None:
    decision = _evaluate(arguments={**VALID_ARGUMENTS, "endpoint": endpoint})

    assert decision.status == "deny"
    assert decision.allowed is False


def test_missing_endpoint_is_denied() -> None:
    decision = _evaluate(arguments={"model_adapter": "ollama"})

    assert decision.status == "deny"


def test_non_ollama_adapter_is_denied() -> None:
    decision = _evaluate(arguments={**VALID_ARGUMENTS, "model_adapter": "cloud"})

    assert decision.status == "deny"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("network_scope", "public"),
        ("external_side_effects", True),
        ("external_side_effects", 0),
        ("credentials_required", True),
        ("credentials_required", 0),
        ("execution_scope", "tool_execution"),
        ("runtime_route", "direct"),
    ],
)
def test_unbounded_policy_context_is_denied(field: str, value: Any) -> None:
    decision = _evaluate(policy_context={**VALID_CONTEXT, field: value})

    assert decision.status == "deny"
    assert decision.allowed is False


@pytest.mark.parametrize("missing_field", list(VALID_CONTEXT))
def test_missing_policy_context_field_is_denied(missing_field: str) -> None:
    context = dict(VALID_CONTEXT)
    context.pop(missing_field)

    assert _evaluate(policy_context=context).status == "deny"


@pytest.mark.parametrize(
    "action",
    [
        "unknown.action",
        "arc.external_email_send",
        "arc.file_mutation",
        "arc.device_control",
        "arc.robotics_action",
    ],
)
def test_other_actions_remain_denied(action: str) -> None:
    decision = _evaluate(action=action)

    assert decision.status == "deny"
    assert decision.allowed is False


def test_valid_policy_performs_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Guardian policy must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", unexpected_network)

    assert _evaluate().status == "allow"
