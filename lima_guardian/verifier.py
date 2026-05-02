"""Standalone rule-based verification engine for LIMA Guardian."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from lima_guardian.config import GuardianConfig, get_config

_DEFAULT_UNSAFE_PATTERNS = (
    r"password\s*[:=]",
    r"api[_ -]?key\s*[:=]",
    r"private[_ -]?key",
    r"drop\s+table",
    r"rm\s+-rf",
)


class VerificationStatus(str, Enum):
    PASS = "pass"
    REVIEW = "review"
    FAIL = "fail"


@dataclass(frozen=True)
class VerificationRequest:
    subject: str
    content: str
    confidence: float = 0.5
    expected_facts: list[str] = field(default_factory=list)
    conflicting_facts: list[str] = field(default_factory=list)
    forbidden_patterns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    confidence: float
    summary: str
    evidence: list[dict[str, str]]
    recommended_next_action: str | None = None


def _emit_verification_event(
    result: VerificationResult,
    request: VerificationRequest,
    cfg: GuardianConfig,
) -> None:
    try:
        if cfg.on_verification_event is not None:
            cfg.on_verification_event(
                "verification.completed",
                request.subject,
                {
                    "status": result.status.value,
                    "confidence": result.confidence,
                    "summary": result.summary,
                    "evidence": result.evidence,
                    "recommended_next_action": result.recommended_next_action,
                },
            )
    except Exception:
        pass


def verify_request(
    request: VerificationRequest,
    *,
    cfg: GuardianConfig | None = None,
) -> VerificationResult:
    if cfg is None:
        cfg = get_config()

    content = " ".join((request.content or "").split()).strip()
    lowered = content.lower()
    evidence: list[dict[str, str]] = []
    for fact in request.expected_facts:
        if fact and fact.lower() in lowered:
            evidence.append({"type": "expected_fact", "detail": fact})

    unsafe_patterns = list(_DEFAULT_UNSAFE_PATTERNS)
    unsafe_patterns.extend(pattern for pattern in request.forbidden_patterns if pattern)
    for pattern in unsafe_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            result = VerificationResult(
                status=VerificationStatus.FAIL,
                confidence=0.98,
                summary="Unsafe or forbidden content was detected.",
                evidence=evidence + [{"type": "unsafe_pattern", "detail": pattern}],
                recommended_next_action="Block the content and require a safer replacement.",
            )
            _emit_verification_event(result, request, cfg)
            return result

    for fact in request.conflicting_facts:
        if fact and fact.lower() in lowered:
            result = VerificationResult(
                status=VerificationStatus.REVIEW,
                confidence=max(0.2, min(request.confidence, 0.74)),
                summary="Potentially conflicting content requires review.",
                evidence=evidence + [{"type": "conflict", "detail": fact}],
                recommended_next_action="Review the conflicting statement before trusting it.",
            )
            _emit_verification_event(result, request, cfg)
            return result

    if request.confidence < 0.75:
        result = VerificationResult(
            status=VerificationStatus.REVIEW,
            confidence=max(0.2, min(request.confidence, 0.74)),
            summary="Confidence is too low for automatic acceptance.",
            evidence=evidence,
            recommended_next_action="Gather stronger evidence or request human review.",
        )
        _emit_verification_event(result, request, cfg)
        return result

    result = VerificationResult(
        status=VerificationStatus.PASS,
        confidence=max(0.75, min(request.confidence, 1.0)),
        summary="Content passed the configured verification checks.",
        evidence=evidence or [{"type": "content", "detail": content[:220]}],
    )
    _emit_verification_event(result, request, cfg)
    return result


def verify_fact(
    *,
    fact: str,
    confidence: float = 0.5,
    conflicting_facts: list[str] | None = None,
    cfg: GuardianConfig | None = None,
) -> VerificationResult:
    return verify_request(
        VerificationRequest(
            subject="fact",
            content=fact,
            confidence=confidence,
            conflicting_facts=conflicting_facts or [],
        ),
        cfg=cfg,
    )
