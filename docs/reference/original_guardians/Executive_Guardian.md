# Executive_Guardian

## Repo URL

- https://github.com/armpit-symphony/Executive_Guardian

## Original Purpose

Executive Guardian was a thin execution-discipline layer for OpenClaw. Its job was to wrap high-risk actions with decision records, budget enforcement, validation, and post-action logging without directly mutating other Guardian subsystems.

## Useful Concepts To Remember

- Treat high-risk tool calls as guarded execution paths rather than ordinary helper functions.
- Use a narrow allowlist for risky actions such as command execution, file writes, and external requests.
- Separate decision capture, budget locking, execution, validation, and logging into explicit stages.
- Keep enforcement behind a feature flag for staged rollout.
- Preserve non-invasive boundaries so execution governance does not silently alter memory or session logs.

## What NOT To Copy Directly

- The legacy `guardian.py` implementation or CLI wrappers.
- OpenClaw-specific preload hooks, file paths, and workspace assumptions.
- Legacy schema-adaptation code written around older Executive Layer variants.
- Any operational coupling that depends on filesystem log layouts from the original environment.

## Possible Future LIMA Ideas

- A typed execution policy layer with explicit tool risk classes.
- First-class decision artifacts stored in LIMA-native persistence rather than filesystem conventions.
- Budget and approval hooks shared with task scheduling and cost governance.
- Validator interfaces that can enforce stronger postconditions for sensitive actions.

## Current LIMA Replacement/Status

- In this repository, the closest replacement is the extracted executive module under `app/services/guardian/executive.py` and the simplified public surface in `guardian/executive.py`.
- Status: historical reference only. Do not revive the original standalone repo as a runtime dependency.
