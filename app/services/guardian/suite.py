"""Unified Guardian suite entrypoint for Sparkbot.

This file provides a single import surface for the Guardian stack so the
integration can be treated as one suite even though some implementation modules
still depend on Sparkbot runtime packages or optional dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from types import SimpleNamespace
from typing import Any


_OPTIONAL_COMPONENT_FALLBACKS: dict[str, tuple[str, ...]] = {
    "meeting_recorder": ("generate_meeting_notes",),
    "task_guardian": ("list_tasks",),
    "token_guardian": ("route_model",),
}


@dataclass(frozen=True)
class GuardianComponent:
    name: str
    module: Any
    description: str


@dataclass(frozen=True)
class GuardianSuite:
    auth: Any
    executive: Any
    meeting_recorder: Any
    memory: Any
    pending_approvals: Any
    policy: Any
    task_guardian: Any
    token_guardian: Any
    vault: Any
    verifier: Any

    def components(self) -> tuple[GuardianComponent, ...]:
        return (
            GuardianComponent("auth", self.auth, "Guardian authority, operator identity, break-glass, and session gating."),
            GuardianComponent("executive", self.executive, "Executive journaling and guarded execution wrappers."),
            GuardianComponent("meeting_recorder", self.meeting_recorder, "Meeting and decision artifact generation."),
            GuardianComponent("memory", self.memory, "Memory Guardian adapter and recall utilities."),
            GuardianComponent("pending_approvals", self.pending_approvals, "Pending approval storage for confirmation-gated actions."),
            GuardianComponent("policy", self.policy, "Policy registry and tool-use decision engine."),
            GuardianComponent("task_guardian", self.task_guardian, "Scheduled Guardian tasks and run history."),
            GuardianComponent("token_guardian", self.token_guardian, "Routing telemetry and model-selection guardrails."),
            GuardianComponent("vault", self.vault, "Guardian Authority Vault secret storage and reveal controls."),
            GuardianComponent("verifier", self.verifier, "Output verification and post-action review utilities."),
        )

    def inventory(self) -> list[dict[str, str]]:
        return [
            {
                "name": component.name,
                "module": getattr(component.module, "__name__", component.name),
                "description": component.description,
            }
            for component in self.components()
        ]


def _unavailable_component(component_name: str, missing: Exception) -> Any:
    def unavailable(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(
            f"Guardian component '{component_name}' is unavailable because optional "
            f"Sparkbot runtime dependencies are missing: {missing}"
        ) from missing

    attrs = {name: unavailable for name in _OPTIONAL_COMPONENT_FALLBACKS.get(component_name, ())}
    attrs["__name__"] = f"app.services.guardian.{component_name}.unavailable"
    attrs["__guardian_unavailable_reason__"] = repr(missing)
    return SimpleNamespace(**attrs)


def _load_component(component_name: str) -> Any:
    try:
        return import_module(f"app.services.guardian.{component_name}")
    except ModuleNotFoundError as exc:
        if component_name in _OPTIONAL_COMPONENT_FALLBACKS:
            return _unavailable_component(component_name, exc)
        raise


guardian_suite = GuardianSuite(
    auth=_load_component("auth"),
    executive=_load_component("executive"),
    meeting_recorder=_load_component("meeting_recorder"),
    memory=_load_component("memory"),
    pending_approvals=_load_component("pending_approvals"),
    policy=_load_component("policy"),
    task_guardian=_load_component("task_guardian"),
    token_guardian=_load_component("token_guardian"),
    vault=_load_component("vault"),
    verifier=_load_component("verifier"),
)


def get_guardian_suite() -> GuardianSuite:
    return guardian_suite


def guardian_suite_inventory() -> list[dict[str, str]]:
    return guardian_suite.inventory()


__all__ = [
    "GuardianComponent",
    "GuardianSuite",
    "get_guardian_suite",
    "guardian_suite",
    "guardian_suite_inventory",
]
