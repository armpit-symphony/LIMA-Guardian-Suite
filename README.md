# Guardian Suite

This repo centralizes the Guardian stack extracted from Sparkbot into one place.

## Layout

- `lima_guardian/`
  Standalone Guardian modules extracted from Sparkbot behind explicit
  configuration. PR 1 includes Vault + Auth core with Fernet encryption,
  configurable env prefix, configurable data directory, and no Sparkbot
  dependencies.
- `app/services/guardian/`
  The full Guardian package, preserved under the original Sparkbot import path.
- `tests/services/test_guardian_suite.py`
  Boundary test for the unified suite entrypoint.
- `guardian_suite_integration.md`
  Original integration plan and sequencing notes.

## What Is Included

Standalone `lima_guardian` modules:

- `config`
- `auth`
- `token_guardian`
- `verifier`
- `improvement`
- `policy`
- `pending_approvals`
- `spine_models`
- `spine_interfaces`
- `spine_events`
- `spine_producers`
- `spine_store_sqlite`
- `vault`

Preserved Sparkbot-layout modules:

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

The `lima_guardian` package is the standalone extraction path. It must not
downgrade Sparkbot behavior; Vault uses `cryptography.fernet.Fernet`, Auth keeps
PBKDF2 PIN hashes and in-memory break-glass sessions, and tests must run without
importing Sparkbot.

The single unified entrypoint is:

- `app.services.guardian.suite`

Use `get_guardian_suite()` or `guardian_suite_inventory()` from:

- `app.services.guardian`
