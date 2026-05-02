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

## Important

This extraction preserves the original module layout, but some modules still depend on Sparkbot packages such as `app.crud`, `app.models`, and selected chat/tool routes. This repo is the consolidated source of the suite, not yet a fully decoupled standalone package.

The single unified entrypoint is:

- `app.services.guardian.suite`

Use `get_guardian_suite()` or `guardian_suite_inventory()` from:

- `app.services.guardian`
