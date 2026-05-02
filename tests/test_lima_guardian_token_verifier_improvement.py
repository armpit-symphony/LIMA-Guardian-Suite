from __future__ import annotations

import importlib
from pathlib import Path

from lima_guardian.config import GuardianConfig
from lima_guardian.improvement import list_feedback, record_feedback, summarize_feedback
from lima_guardian.token_guardian import (
    ModelMetadata,
    TokenDecisionAction,
    TokenRequest,
    evaluate_token_request,
)
from lima_guardian.verifier import VerificationRequest, VerificationStatus, verify_fact, verify_request


def _registry() -> dict[str, ModelMetadata]:
    return {
        "cheap-safe": ModelMetadata(
            provider="test",
            model_name="cheap-safe",
            max_input_tokens=4000,
            max_output_tokens=1000,
            cost_per_1k_input=0.001,
            cost_per_1k_output=0.002,
            capabilities={"chat", "safe"},
        ),
        "large-safe": ModelMetadata(
            provider="test",
            model_name="large-safe",
            max_input_tokens=32000,
            max_output_tokens=4000,
            cost_per_1k_input=0.02,
            cost_per_1k_output=0.03,
            capabilities={"chat", "safe", "analysis"},
        ),
    }


def test_token_request_allowed_under_budget(tmp_path):
    cfg = GuardianConfig(
        env_prefix="TEST_LIMA",
        data_dir=tmp_path,
        token_budget_review_threshold=1.0,
    )
    decision = evaluate_token_request(
        TokenRequest(
            requested_model="cheap-safe",
            input_tokens=1000,
            output_tokens=500,
            budget_remaining=2.0,
        ),
        cfg=cfg,
        registry=_registry(),
    )

    assert decision.action == TokenDecisionAction.ALLOW
    assert decision.selected_model == "cheap-safe"


def test_token_request_denied_over_max_tokens(tmp_path):
    cfg = GuardianConfig(env_prefix="TEST_LIMA", data_dir=tmp_path)
    decision = evaluate_token_request(
        TokenRequest(
            requested_model="cheap-safe",
            input_tokens=5000,
            output_tokens=10,
        ),
        cfg=cfg,
        registry=_registry(),
    )

    assert decision.action == TokenDecisionAction.DENY


def test_token_request_reviewed_over_budget_threshold(tmp_path):
    cfg = GuardianConfig(
        env_prefix="TEST_LIMA",
        data_dir=tmp_path,
        token_budget_review_threshold=0.001,
    )
    decision = evaluate_token_request(
        TokenRequest(
            requested_model="cheap-safe",
            input_tokens=1000,
            output_tokens=500,
        ),
        cfg=cfg,
        registry=_registry(),
    )

    assert decision.action == TokenDecisionAction.REVIEW
    assert "threshold" in decision.reason.lower()


def test_unknown_model_reviewed_safely(tmp_path):
    cfg = GuardianConfig(env_prefix="TEST_LIMA", data_dir=tmp_path)
    decision = evaluate_token_request(
        TokenRequest(
            requested_model="unknown-model",
            input_tokens=100,
            output_tokens=50,
        ),
        cfg=cfg,
        registry=_registry(),
    )

    assert decision.action in {TokenDecisionAction.REVIEW, TokenDecisionAction.DENY}
    assert decision.model_known is False


def test_verifier_passes_high_confidence_safe_fact(tmp_path):
    events: list[tuple[str, str, dict]] = []
    cfg = GuardianConfig(
        env_prefix="TEST_LIMA",
        data_dir=tmp_path,
        on_verification_event=lambda event_type, subject, payload: events.append(
            (event_type, subject, payload)
        ),
    )

    result = verify_fact(
        fact="The deployment target is staging.",
        confidence=0.95,
        cfg=cfg,
    )

    assert result.status == VerificationStatus.PASS
    assert events[0][0] == "verification.completed"


def test_verifier_reviews_low_confidence_or_conflict(tmp_path):
    cfg = GuardianConfig(env_prefix="TEST_LIMA", data_dir=tmp_path)
    low_confidence = verify_fact(
        fact="The deployment target is staging.",
        confidence=0.4,
        cfg=cfg,
    )
    conflicting = verify_request(
        VerificationRequest(
            subject="fact",
            content="The deployment target is production.",
            confidence=0.9,
            conflicting_facts=["production"],
        ),
        cfg=cfg,
    )

    assert low_confidence.status == VerificationStatus.REVIEW
    assert conflicting.status == VerificationStatus.REVIEW


def test_verifier_fails_unsafe_content(tmp_path):
    cfg = GuardianConfig(env_prefix="TEST_LIMA", data_dir=tmp_path)
    result = verify_request(
        VerificationRequest(
            subject="unsafe",
            content="api_key=secret-value",
            confidence=0.95,
        ),
        cfg=cfg,
    )

    assert result.status == VerificationStatus.FAIL


def test_improvement_loop_records_correction(tmp_path):
    cfg = GuardianConfig(env_prefix="TEST_LIMA", data_dir=tmp_path)
    event = record_feedback(
        event_type="correction",
        label="facts",
        source_text="The meeting is on Tuesday.",
        corrected_text="The meeting is on Wednesday.",
        cfg=cfg,
    )
    events = list_feedback(cfg=cfg)

    assert event.event_type == "correction"
    assert events[0].corrected_text == "The meeting is on Wednesday."


def test_improvement_loop_summarizes_feedback_events(tmp_path):
    cfg = GuardianConfig(env_prefix="TEST_LIMA", data_dir=tmp_path)
    record_feedback(
        event_type="correction",
        label="facts",
        source_text="One",
        corrected_text="Two",
        cfg=cfg,
    )
    record_feedback(
        event_type="feedback",
        label="routing",
        source_text="Prefer cheaper model.",
        cfg=cfg,
    )

    summary = summarize_feedback(cfg=cfg)

    assert summary["total_events"] == 2
    assert summary["corrections_recorded"] == 1
    assert summary["event_types"]["correction"] == 1
    assert summary["labels"]["routing"] == 1


def test_standalone_modules_do_not_import_app_or_sparkbot():
    modules = [
        importlib.import_module("lima_guardian.token_guardian"),
        importlib.import_module("lima_guardian.verifier"),
        importlib.import_module("lima_guardian.improvement"),
    ]
    for module in modules:
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "from app" not in source
        assert "import app" not in source
        assert "import sparkbot" not in source.lower()
