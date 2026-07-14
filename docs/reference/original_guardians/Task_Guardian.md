# Task_Guardian

## Repo URL

- https://github.com/armpit-symphony/Task_Guardian

## Original Purpose

Task Guardian was a safe, agent-oriented scheduler and executor for OpenClaw-style stacks. Its package metadata and module layout show a focus on cron-style scheduling, task execution, persistent task state, and integrations with executive and memory layers.

## Useful Concepts To Remember

- Separate scheduling, execution, storage, and CLI concerns into distinct modules.
- Treat recurring automation as a governed subsystem instead of ad hoc background scripts.
- Keep task state explicit and durable so scheduled work can be audited and resumed.
- Design integration points for memory and executive governance rather than embedding those concerns everywhere.
- Represent user workflows as named jobs instead of hard-coded one-off automations.

## What NOT To Copy Directly

- The legacy scheduler, executor, store, or CLI source files.
- The original `bin/` task scripts and any environment-specific example jobs.
- Local virtual environment artifacts, sqlite files, or logs from the original repo.
- OpenClaw-specific assumptions baked into the standalone package layout.

## Possible Future LIMA Ideas

- A LIMA-native task registry with policy-aware scheduling.
- Approval gates for high-risk or high-cost recurring jobs.
- Shared task telemetry that links scheduled runs to memory, executive, and token decisions.
- Safer user-facing task templates with explicit permissions and budgets.

## Current LIMA Replacement/Status

- In this repository, the nearest replacement is `app/services/guardian/task_guardian.py` plus the simplified wrapper in `guardian/task.py`.
- Status: historical reference only. Keep future task orchestration inside LIMA-owned modules rather than restoring the original standalone package.
