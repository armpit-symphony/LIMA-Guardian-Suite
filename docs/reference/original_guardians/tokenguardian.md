# tokenguardian

## Repo URL

- https://github.com/armpit-symphony/tokenguardian

## Original Purpose

tokenguardian was a unified cost-optimization and routing pipeline for OpenClaw-powered systems. It combined query classification, prompt optimization, token and cost monitoring, model routing, fallback behavior, and operational daemon tooling.

## Useful Concepts To Remember

- Put routing, optimization, and cost observation into one governance pipeline.
- Attribute spend by session, model, and agent so costs are explainable.
- Use confidence-based fallback to route uncertain cases to safer models.
- Support shadow mode before enabling live cost or routing enforcement.
- Keep model pricing and routing rules configurable instead of hard-coded.

## What NOT To Copy Directly

- The legacy daemon scripts, shell installers, and systemd units.
- Provider-specific model cost tables and environment-specific configuration.
- Standalone monitoring logs, burn-in drivers, or operational runbooks tied to the old deployment.
- The original OpenClaw-specific router integration code.

## Possible Future LIMA Ideas

- Centralized model routing policy with explicit budget envelopes.
- Cost telemetry shared with task execution and executive approvals.
- Shadow-mode rollout support for routing changes before live enforcement.
- Provider-agnostic pricing and fallback configuration stored in LIMA-native config.

## Current LIMA Replacement/Status

- In this repository, the closest replacement is `app/services/guardian/token_guardian.py`, the vendored `app/services/guardian/tokenguardian/` package, and the simplified wrapper in `guardian/token.py`.
- Status: historical reference only. Reuse concepts, not the original standalone operational stack.
