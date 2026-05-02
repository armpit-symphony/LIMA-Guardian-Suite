"""Standalone token, cost, and routing guard for LIMA Guardian."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping

from lima_guardian.config import GuardianConfig, get_config


class TokenDecisionAction(str, Enum):
    ALLOW = "allow"
    REVIEW = "review"
    DENY = "deny"


@dataclass(frozen=True)
class ModelMetadata:
    provider: str
    model_name: str
    max_input_tokens: int
    max_output_tokens: int
    cost_per_1k_input: float
    cost_per_1k_output: float
    capabilities: set[str] = field(default_factory=set)
    enabled: bool = True


@dataclass(frozen=True)
class TokenRequest:
    requested_model: str
    input_tokens: int
    output_tokens: int = 0
    required_capabilities: set[str] = field(default_factory=set)
    budget_remaining: float | None = None
    budget_review_threshold: float | None = None
    candidate_models: list[str] | None = None


@dataclass(frozen=True)
class RoutingDecision:
    requested_model: str
    selected_model: str | None
    action: TokenDecisionAction
    reason: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost: float
    model_known: bool
    capabilities_satisfied: bool
    candidate_models: list[str]
    fallback_triggered: bool = False


def default_model_registry() -> dict[str, ModelMetadata]:
    return {
        "gpt-4o-mini": ModelMetadata(
            provider="openai",
            model_name="gpt-4o-mini",
            max_input_tokens=128_000,
            max_output_tokens=16_384,
            cost_per_1k_input=0.00015,
            cost_per_1k_output=0.0006,
            capabilities={"chat", "reasoning", "tool_use"},
        ),
        "gpt-4.1": ModelMetadata(
            provider="openai",
            model_name="gpt-4.1",
            max_input_tokens=128_000,
            max_output_tokens=32_768,
            cost_per_1k_input=0.002,
            cost_per_1k_output=0.008,
            capabilities={"chat", "reasoning", "tool_use", "coding"},
        ),
        "claude-3-5-sonnet": ModelMetadata(
            provider="anthropic",
            model_name="claude-3-5-sonnet",
            max_input_tokens=200_000,
            max_output_tokens=8_192,
            cost_per_1k_input=0.003,
            cost_per_1k_output=0.015,
            capabilities={"chat", "reasoning", "tool_use", "analysis"},
        ),
    }


def _load_registry_from_path(path: Path) -> dict[str, ModelMetadata]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    rows: Iterable[dict] | Mapping[str, dict]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload
    else:
        return {}

    registry: dict[str, ModelMetadata] = {}
    if isinstance(rows, dict):
        iterator = rows.items()
        for model_name, item in iterator:
            if not isinstance(item, dict):
                continue
            registry[str(model_name)] = ModelMetadata(
                provider=str(item.get("provider") or "unknown"),
                model_name=str(item.get("model_name") or model_name),
                max_input_tokens=max(int(item.get("max_input_tokens") or 0), 0),
                max_output_tokens=max(int(item.get("max_output_tokens") or 0), 0),
                cost_per_1k_input=max(float(item.get("cost_per_1k_input") or 0.0), 0.0),
                cost_per_1k_output=max(float(item.get("cost_per_1k_output") or 0.0), 0.0),
                capabilities={str(cap).strip() for cap in item.get("capabilities") or [] if str(cap).strip()},
                enabled=bool(item.get("enabled", True)),
            )
        return registry

    for item in rows:
        if not isinstance(item, dict):
            continue
        model_name = str(item.get("model_name") or "").strip()
        if not model_name:
            continue
        registry[model_name] = ModelMetadata(
            provider=str(item.get("provider") or "unknown"),
            model_name=model_name,
            max_input_tokens=max(int(item.get("max_input_tokens") or 0), 0),
            max_output_tokens=max(int(item.get("max_output_tokens") or 0), 0),
            cost_per_1k_input=max(float(item.get("cost_per_1k_input") or 0.0), 0.0),
            cost_per_1k_output=max(float(item.get("cost_per_1k_output") or 0.0), 0.0),
            capabilities={str(cap).strip() for cap in item.get("capabilities") or [] if str(cap).strip()},
            enabled=bool(item.get("enabled", True)),
        )
    return registry


def load_model_registry(
    *,
    cfg: GuardianConfig | None = None,
    registry: Mapping[str, ModelMetadata] | None = None,
) -> dict[str, ModelMetadata]:
    if registry is not None:
        return dict(registry)
    if cfg is None:
        cfg = get_config()
    loaded = _load_registry_from_path(Path(cfg.token_model_registry_path))
    if loaded:
        return loaded
    return default_model_registry()


def estimate_request_cost(model: ModelMetadata, *, input_tokens: int, output_tokens: int) -> float:
    input_cost = (max(input_tokens, 0) / 1000.0) * model.cost_per_1k_input
    output_cost = (max(output_tokens, 0) / 1000.0) * model.cost_per_1k_output
    return round(input_cost + output_cost, 6)


def _supports_capabilities(model: ModelMetadata, required_capabilities: set[str]) -> bool:
    if not required_capabilities:
        return True
    return required_capabilities.issubset(model.capabilities)


def _candidate_models(request: TokenRequest, registry: Mapping[str, ModelMetadata]) -> list[str]:
    if request.candidate_models:
        return [model for model in request.candidate_models if model in registry]
    return list(registry.keys())


def evaluate_token_request(
    request: TokenRequest,
    *,
    cfg: GuardianConfig | None = None,
    registry: Mapping[str, ModelMetadata] | None = None,
) -> RoutingDecision:
    if cfg is None:
        cfg = get_config()
    registry_map = load_model_registry(cfg=cfg, registry=registry)
    requested = registry_map.get(request.requested_model)
    candidates = _candidate_models(request, registry_map)

    if requested is None:
        return RoutingDecision(
            requested_model=request.requested_model,
            selected_model=None,
            action=TokenDecisionAction.REVIEW,
            reason=f"Model '{request.requested_model}' is unknown to the current registry.",
            estimated_input_tokens=max(request.input_tokens, 0),
            estimated_output_tokens=max(request.output_tokens, 0),
            estimated_cost=0.0,
            model_known=False,
            capabilities_satisfied=False,
            candidate_models=candidates,
        )

    capable_candidates = [
        registry_map[name]
        for name in candidates
        if registry_map[name].enabled and _supports_capabilities(registry_map[name], request.required_capabilities)
    ]
    capabilities_satisfied = _supports_capabilities(requested, request.required_capabilities)
    selected = requested
    fallback_triggered = False
    if not capabilities_satisfied and capable_candidates:
        selected = min(
            capable_candidates,
            key=lambda model: estimate_request_cost(
                model,
                input_tokens=request.input_tokens,
                output_tokens=request.output_tokens,
            ),
        )
        fallback_triggered = selected.model_name != requested.model_name
        capabilities_satisfied = True

    if not capabilities_satisfied:
        return RoutingDecision(
            requested_model=request.requested_model,
            selected_model=requested.model_name,
            action=TokenDecisionAction.REVIEW,
            reason="Requested model does not satisfy the required capabilities.",
            estimated_input_tokens=max(request.input_tokens, 0),
            estimated_output_tokens=max(request.output_tokens, 0),
            estimated_cost=estimate_request_cost(
                requested,
                input_tokens=request.input_tokens,
                output_tokens=request.output_tokens,
            ),
            model_known=True,
            capabilities_satisfied=False,
            candidate_models=candidates,
        )

    if request.input_tokens > selected.max_input_tokens or request.output_tokens > selected.max_output_tokens:
        return RoutingDecision(
            requested_model=request.requested_model,
            selected_model=selected.model_name,
            action=TokenDecisionAction.DENY,
            reason=f"Token request exceeds limits for model '{selected.model_name}'.",
            estimated_input_tokens=max(request.input_tokens, 0),
            estimated_output_tokens=max(request.output_tokens, 0),
            estimated_cost=estimate_request_cost(
                selected,
                input_tokens=request.input_tokens,
                output_tokens=request.output_tokens,
            ),
            model_known=True,
            capabilities_satisfied=True,
            candidate_models=candidates,
            fallback_triggered=fallback_triggered,
        )

    estimated_cost = estimate_request_cost(
        selected,
        input_tokens=request.input_tokens,
        output_tokens=request.output_tokens,
    )
    review_threshold = (
        request.budget_review_threshold
        if request.budget_review_threshold is not None
        else cfg.token_budget_review_threshold
    )

    if request.budget_remaining is not None and estimated_cost > request.budget_remaining:
        return RoutingDecision(
            requested_model=request.requested_model,
            selected_model=selected.model_name,
            action=TokenDecisionAction.REVIEW,
            reason="Estimated cost exceeds the remaining budget.",
            estimated_input_tokens=max(request.input_tokens, 0),
            estimated_output_tokens=max(request.output_tokens, 0),
            estimated_cost=estimated_cost,
            model_known=True,
            capabilities_satisfied=True,
            candidate_models=candidates,
            fallback_triggered=fallback_triggered,
        )

    if review_threshold is not None and estimated_cost > review_threshold:
        return RoutingDecision(
            requested_model=request.requested_model,
            selected_model=selected.model_name,
            action=TokenDecisionAction.REVIEW,
            reason="Estimated cost crossed the configured review threshold.",
            estimated_input_tokens=max(request.input_tokens, 0),
            estimated_output_tokens=max(request.output_tokens, 0),
            estimated_cost=estimated_cost,
            model_known=True,
            capabilities_satisfied=True,
            candidate_models=candidates,
            fallback_triggered=fallback_triggered,
        )

    reason = f"Token request is within limits for model '{selected.model_name}'."
    if fallback_triggered:
        reason = (
            f"Requested model lacked required capabilities; routed to '{selected.model_name}' "
            "within the configured limits."
        )
    return RoutingDecision(
        requested_model=request.requested_model,
        selected_model=selected.model_name,
        action=TokenDecisionAction.ALLOW,
        reason=reason,
        estimated_input_tokens=max(request.input_tokens, 0),
        estimated_output_tokens=max(request.output_tokens, 0),
        estimated_cost=estimated_cost,
        model_known=True,
        capabilities_satisfied=True,
        candidate_models=candidates,
        fallback_triggered=fallback_triggered,
    )
