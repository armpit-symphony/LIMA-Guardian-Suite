# Guardian Suite

This repo centralizes the Guardian stack extracted from Sparkbot into one place.

## Historical References

These are historical documentation references only. Current product code lives in `lima_guardian/`.

See `docs/reference/original_guardians/` for documentation-only notes on the original standalone Guardian repositories.

## Layout

- `app/services/guardian/`
  The full Guardian package, preserved under the original Sparkbot import path.
- `tests/services/test_guardian_suite.py`
  Boundary test for the unified suite entrypoint.
- `guardian_suite_integration.md`
  Original integration plan and sequencing notes.

## What Is Included

- `auth`
- `executive`
- `meeting_recorder`
- `memory`
- `pending_approvals`
- `policy`
- `suite`
- `task_guardian`
- `token_guardian`
- `vault`
- `verifier`
- vendored `memory_os`
- vendored `tokenguardian`

## Standalone Public API

Install with `python -m pip install -e .`, then import
`GuardianEvaluationRequest`, `GuardianDecision`, and
`evaluate_guardian_request` from `guardian_core`.

This API evaluates policy and returns a Guardian-owned `decision_id`; it never
executes the requested action. The legacy `app.services.guardian` tree remains
Sparkbot-coupled source and is not a supported installed entrypoint.
