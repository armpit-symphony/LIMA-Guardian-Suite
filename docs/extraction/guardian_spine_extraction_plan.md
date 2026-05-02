# Guardian Spine Extraction Plan

Date: 2026-05-01
Status: Planning only
Source of truth: Sparkbot remains the authoritative implementation for Guardian Spine
Target repo: `LIMA-Guardian-Suite`
Target branch: `pr4-guardian-spine-extraction-plan`

## 1. Executive Summary

### What Guardian Spine does in Sparkbot

Guardian Spine is Sparkbot's canonical work-state ledger. It receives structured events from chat intake, approvals, breakglass flows, task guardian runs, memory resurfacing, meeting artifacts, worker status updates, room lifecycle changes, and explicit project lifecycle operations. It stores those events and the derived task/project state in a dedicated SQLite database, mirrors selected state into markdown artifacts, and serves both room-scoped and operator-scoped inspection APIs consumed by the React dashboard.

In practice, Spine is not just an event log. It is also:

- the canonical task catalog for Guardian/Task Master
- the canonical project catalog for Project Executive
- the approval mirror used by queue views
- the lineage graph for task dependencies, duplicates, and handoffs
- the bridge between Sparkbot ORM state and Guardian state

### Why it is too risky to extract in one PR

Spine is too large and too coupled to move safely in one extraction PR because it mixes:

- event ingestion
- canonical SQLite persistence
- schema migration logic
- task/project derivation heuristics
- markdown mirror generation
- Sparkbot ORM synchronization
- operator routes
- React dashboard assumptions

The current file is about 3.8k lines and owns eight SQLite tables plus additive schema migrations. It is called from `crud.py`, `pending_approvals.py`, `vault.py`, `token_guardian.py`, `memory.py`, `executive.py`, `task_guardian.py`, `project_executive.py`, `task_master_adapter.py`, room routes, and the dedicated Spine router. Pulling all of that at once would create high risk of data loss, approval-state regressions, dashboard mismatches, and duplicate lifecycle writes.

### What must be separated first

The safe order is:

1. Define interfaces and event models without changing runtime behavior.
2. Separate generic Spine storage concerns from Sparkbot-specific adapters.
3. Isolate ORM synchronization and dashboard/API surfaces behind adapter boundaries.
4. Move storage and event models only after tests and migration dry-runs exist.

The smallest safe next Spine PR after planning is `PR 4A: introduce Spine interfaces only`.

## 2. Spine Runtime Inventory

### Primary Spine files

| File | Purpose | Public functions/classes | Callers | Routes/endpoints | Background jobs | Tables/models used | Env vars used | Frontend/dashboard deps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `backend/app/services/guardian/spine.py` | Canonical Spine task/project/event ledger, queue derivation, event ingestion, mirror generation | `SpineTask`, `SpineEvent`, `SpineHandoff`, `SpineProject`, `SpineApproval`, `SpineLink`, `SpineProjectEvent`, `SpineSourceReference`, `SpineProjectInput`, `SpineTaskInput`, `SpineSubsystemEvent`, `SpineProducerRegistration`, `register_spine_producer()`, `list_registered_spine_producers()`, `capture_message()`, `capture_meeting_artifact()`, `sync_chat_task_created()`, `sync_chat_task_status()`, `list_spine_tasks()`, `list_spine_events()`, `get_spine_project()`, `list_spine_projects()`, `get_spine_task()`, `list_project_tasks()`, `list_orphan_tasks()`, `list_spine_approvals()`, `list_spine_links()`, `list_project_handoffs()`, `list_project_events()`, `get_task_lineage()`, `list_spine_handoffs()`, `get_spine_overview()`, queue/signal listing helpers, `get_project_workload_summary()`, `get_task_master_overview()`, `ingest_subsystem_event()`, `ingest_memory_signal()`, `ingest_executive_decision()`, `get_spine_task_by_chat_task_id()`, `emit_task_master_action()`, `emit_approval_event()`, `emit_breakglass_event()`, `ingest_task_guardian_result()`, `emit_room_lifecycle_event()`, `emit_project_lifecycle_event()`, `emit_handoff_event()`, `emit_meeting_output_event()`, `emit_worker_status_event()`, project mutation helpers | `crud.py`, `pending_approvals.py`, `vault.py`, `memory.py`, `executive.py`, `task_guardian.py`, `token_guardian.py`, `task_master_adapter.py`, `project_executive.py`, room routes, Spine routes, tests | `/api/v1/chat/rooms/{room_id}/spine/*`, `/api/v1/chat/spine/operator/*` via router | None directly; event-driven only | 8 Spine SQLite tables, plus `ChatTask`, `ChatRoom`, `Session` for sync | `SPARKBOT_GUARDIAN_SPINE_AUTO_CREATE_THRESHOLD`, `SPARKBOT_GUARDIAN_SPINE_REVIEW_THRESHOLD`, `SPARKBOT_GUARDIAN_DATA_DIR` | Backend API consumed by `frontend/src/lib/spine.ts` and `frontend/src/routes/_layout/spine.tsx` |
| `backend/app/api/routes/chat/spine.py` | Room and operator Spine inspection and project mutation API | response models plus 40+ route handlers | React dashboard, operator UI, room inspection calls | Room routes for tasks, events, handoffs, overview, projects, lineage, approvals, task-master overview; operator routes for queues, signals, producers, workload, task detail, and project mutation APIs | None | Reads Spine dataclasses and adapters; writes via `project_executive` | None directly | Primary API contract for dashboard |
| `frontend/src/lib/spine.ts` | Typed API client for Spine operator and guardian endpoints | `SpineTask`, `SpineProject`, `SpineEvent`, `SpineProducer`, `SpineApproval`, `SpineHandoff`, `SpineTaskLineage`, `SpineTMOverview`; fetch helpers such as `fetchSpineTMOverview()`, `fetchSpineQueue()`, `fetchSpineProjects()`, `fetchSpineTaskDetail()` | `frontend/src/routes/_layout/spine.tsx` | Reads `/api/v1/chat/spine/operator/*` and guardian endpoints | None | Depends on route response shapes | None | Yes, this is the dashboard data contract |
| `frontend/src/routes/_layout/spine.tsx` | Guardian Spine operator dashboard | `SpineOps` route component and UI helpers | Browser UI | Uses queue, project, event, producer, breakglass, and vault APIs | Polling/refresh only in browser | Depends on task/project/event/approval shapes from Spine APIs | None | Yes, direct dashboard |
| `backend/tests/services/test_guardian_spine.py` | Spine runtime coverage and regression tests | Spine integration tests | Test runner | None | None | Exercises Spine tables, mirrors, queue derivation, approvals, handoffs, projects, task master round-trip | `SPARKBOT_GUARDIAN_DATA_DIR` in test setup | Indirectly validates API-facing state |

### Direct adapters and dependent producers

| File | Purpose | Public functions/classes | Callers | Routes/endpoints | Background jobs | Tables/models used | Env vars used | Frontend/dashboard deps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `backend/app/services/guardian/task_master_adapter.py` | Task Master execution adapter over Spine queues and task lifecycle events | `TaskMasterQueueSnapshot`, `TaskMasterSpineAdapter`, `overview()`, queue readers, signal readers, `register_created_task()`, `queue_task()`, `assign_task()`, `block_task()`, `complete_task()`, `reopen_task()`, `assign_existing_task()`, `archive_deleted_task()`, `change_status()`, `emit_status_change()` | `crud.py`, task routes, Spine router, tests | Task routes and Spine task-master views | None directly | `ChatTask`, `TaskStatus`, Spine APIs | None directly | Operator task-master overview depends on this adapter's queue semantics |
| `backend/app/services/guardian/project_executive.py` | Explicit project lifecycle adapter over canonical Spine | `ProjectHasOpenTasksError`, `ProjectNotFoundError`, `ProjectExecutiveAdapter`, `create_project()`, `update_metadata()`, `assign_owner()`, `transition_status()`, `archive_project()`, `cancel_project()`, `reopen_project()`, `attach_task()`, `detach_task()`, signal readers | Spine router, tests, potential future project APIs | `/spine/operator/projects*` mutation routes | None | Spine project/task/event state | None directly | Operator project management UI depends on this adapter |
| `backend/app/services/guardian/pending_approvals.py` | Pending approval queue with Spine event mirror | `PendingApproval`, `store_pending_approval()`, `consume_pending_approval()`, `get_pending_approval()`, `discard_pending_approval()`, `list_pending_approvals()` | Guardian routes, tool flows, tests | Guardian approval routes, indirectly visible in Spine queues | TTL pruning only on access | `pending_approvals` SQLite table plus Spine approval/task state | `SPARKBOT_GUARDIAN_DATA_DIR` | Approval-waiting queue and approval signals depend on mirrored events |
| `backend/app/services/guardian/vault.py` | Secret store that emits subsystem events into Spine | `vault_add()`, `vault_use()`, `vault_reveal()`, `vault_update()`, `vault_delete()` and helpers | Guardian routes, token/config flows | Guardian vault routes | None | `vault_entries`, `vault_audit`; emits Spine events | `SPARKBOT_VAULT_KEY`, `SPARKBOT_GUARDIAN_DATA_DIR` | Security/audit visibility via Spine events |
| `backend/app/services/guardian/memory.py` | Memory ledger plus fact/memory event producer | `remember_chat_message()`, `remember_tool_event()`, fact storage flows, retrieval APIs | chat/tool flows, nightly jobs, tests | Memory routes | Memory background and nightly hygiene flows feed signals indirectly | Memory tables/ledger plus emits Spine subsystem events | `SPARKBOT_MEMORY_*` set | Resurfaced queue and memory-derived tasks depend on these events |
| `backend/app/services/guardian/executive.py` | High-risk execution journal and executive decision producer | `exec_with_guard()`, `get_status()` | tool execution flows | Guardian/executive status routes | None | JSONL decision log plus Spine events | `SPARKBOT_EXECUTIVE_GUARDIAN_ENABLED`, `SPARKBOT_GUARDIAN_DATA_DIR` | Executive directive queue depends on these events |
| `backend/app/services/guardian/task_guardian.py` | Scheduled jobs and verifier-driven task progression | `schedule_task()`, `run_task_once()`, `list_tasks()`, `list_runs()`, scheduler loops | startup/background jobs, routes | Guardian task routes | `task_guardian_scheduler()`, `memory_guardian_nightly_scheduler()` | `guardian_tasks`, `guardian_task_runs`, room execution state; emits Spine task events | `SPARKBOT_TASK_GUARDIAN_*` | Task progress/block/completion signals appear in Spine views |
| `backend/app/services/guardian/token_guardian.py` | Model routing telemetry with subsystem events | `route_model()`, `run_shadow_route()`, `get_token_guardian_stats()` | chat/model selection flows | indirect via chat routes | None | vendored routing config plus emits Spine events | `SPARKBOT_TOKEN_GUARDIAN_*` | Token routing can appear in Spine event feed |
| `backend/app/services/guardian/improvement.py` | Outcome scoring and improvement proposal producer | `record_outcome()`, `choose_best_model()`, `reorder_candidate_models()`, `build_promoted_workflow_context()`, `propose_improvement()`, `list_improvement_proposals()` | token routing, workflow adaptation, future ops tools | no dedicated Spine route | None | `outcomes.json`; emits improvement proposal events | `SPARKBOT_IMPROVEMENT_*` | Improvement proposals may surface in event feed |
| `backend/app/crud.py` | Room/message/artifact ORM flows that feed Spine | `create_chat_room()`, `create_chat_message()`, `create_chat_meeting_artifact()`, task mutation helpers call Spine emitters/adapters | room, message, task APIs | room/message/task endpoints | None | `ChatRoom`, `ChatMessage`, `ChatMeetingArtifact`, `ChatTask` plus Spine | None directly | Room lifecycle and message-derived tasks originate here |

### Routes and frontend dependencies

- Room-scoped Spine inspection routes in `backend/app/api/routes/chat/spine.py`:
  `GET /rooms/{room_id}/spine/tasks`, `events`, `handoffs`, `overview`, `projects`, `projects/{project_id}/tasks`, `tasks/orphaned`, `tasks/{task_id}/lineage`, `tasks/{task_id}/approvals`, `projects/{project_id}/handoffs`, `projects/{project_id}/events`, `task-master/overview`
- Operator routes in the same file:
  producers, recent events, 9 queue/signal endpoints, projects/workload, task detail, 8 project mutation endpoints, and 6 project-signal endpoints
- Frontend dependencies:
  `frontend/src/lib/spine.ts` is the typed API contract
  `frontend/src/routes/_layout/spine.tsx` is the dashboard surface that assumes current response shapes, queue names, event fields, and project mutation semantics

## 3. State and Table Inventory

The live Spine schema is wider than the base `CREATE TABLE` block. `_ensure_schema_migrations()` adds columns to tasks, events, and especially projects, then backfills defaults. Extraction must preserve the migrated schema, not just the original DDL.

### `guardian_spine_tasks`

Belongs in: LIMA core store

Fields:
- `task_id` PK
- `room_id`
- `title`
- `summary`
- `project_id`
- `type`
- `priority`
- `status`
- `owner_kind`
- `owner_id`
- `source_kind`
- `source_ref`
- `created_by_guardian`
- `created_by_subsystem` migrated
- `updated_by_subsystem` migrated
- `approval_required`
- `approval_state`
- `confidence`
- `parent_task_id`
- `depends_on_json`
- `tags_json`
- `created_at`
- `updated_at`
- `last_progress_at`
- `closed_at`
- `source_excerpt`
- `chat_task_id`

Relationships:
- one task to many `guardian_spine_events`
- one task to many `guardian_spine_links`
- one task to many `guardian_spine_assignments`
- one task to many `guardian_spine_approvals`
- one task to many `guardian_spine_handoffs`
- optional many-to-one to `guardian_spine_projects`
- optional link to Sparkbot `ChatTask` through `chat_task_id`

Lifecycle events:
- candidate created/normalized
- duplicate detected
- task created/updated/completed/reopened/blocked/queued/assigned
- approval state transitions
- memory resurfacing
- project attach/detach

Migration risks:
- `created_by_subsystem` and `updated_by_subsystem` are added later
- `chat_task_id` is Sparkbot-specific mirror linkage
- status semantics are shared with queue derivation and dashboard filters

### `guardian_spine_events`

Belongs in: LIMA core store

Fields:
- `event_id` PK
- `event_type`
- `occurred_at`
- `room_id` migrated
- `subsystem` migrated
- `actor_kind`
- `actor_id`
- `source_kind`
- `source_ref`
- `correlation_id`
- `task_id`
- `project_id`
- `payload_json`

Relationships:
- optional many-to-one to task
- optional many-to-one to project

Lifecycle events:
- immutable append-only audit/event stream

Migration risks:
- payload redaction must be preserved
- room and subsystem are additive migrated columns
- event readers assume JSON payloads remain parseable

### `guardian_spine_links`

Belongs in: LIMA core store

Fields:
- `id` PK
- `task_id`
- `related_task_id`
- `link_type`
- `created_at`

Relationships:
- task dependency, duplicate, related, mirror lineage

Lifecycle events:
- created when duplicate/dependency/related relationships are inferred or explicit

Migration risks:
- duplicate detection and lineage views depend on exact link semantics

### `guardian_spine_assignments`

Belongs in: split
LIMA core owns assignment history format
Sparkbot adapter owns mapping from Sparkbot users/agents to `owner_kind` and `owner_id`

Fields:
- `id` PK
- `task_id`
- `owner_kind`
- `owner_id`
- `assigned_at`
- `assigned_by`

Relationships:
- one task to many assignment records

Lifecycle events:
- assignment and reassignment history

Migration risks:
- owner identifiers are product-specific

### `guardian_spine_approvals`

Belongs in: split
LIMA core owns approval history shape
Sparkbot adapter owns linkage to pending approval queue and breakglass UX

Fields:
- `id` PK
- `task_id`
- `requester_id`
- `approver_id`
- `approval_method`
- `state`
- `scope_json`
- `expires_at`
- `created_at`
- `updated_at`

Relationships:
- approval mirror associated with task

Lifecycle events:
- required, granted, denied, discarded, expired

Migration risks:
- approval bypass or stale-state regressions if mirror and pending queue diverge

### `guardian_spine_handoffs`

Belongs in: split
LIMA core owns handoff record shape
Sparkbot adapter owns room/task-specific handoff routing and markdown mirrors

Fields:
- `id` PK
- `task_id`
- `room_id`
- `summary`
- `created_at`
- `source_ref`

Relationships:
- one task to many handoffs

Lifecycle events:
- created when escalations or cross-room routing happen

Migration risks:
- room identifiers and handoff mirrors are Sparkbot-specific

### `guardian_spine_projects`

Belongs in: split
LIMA core owns canonical project record
Sparkbot adapter owns room coupling, owner semantics, and downstream mirrors/UI flows

Base fields:
- `project_id` PK
- `room_id`
- `display_name`
- `slug`
- `updated_at`

Migrated live fields:
- `summary`
- `status`
- `source_kind`
- `source_ref`
- `created_by_subsystem`
- `updated_by_subsystem`
- `tags_json`
- `parent_project_id`
- `created_at`
- `owner_kind`
- `owner_id`

Relationships:
- one project to many tasks
- one project to many project events

Lifecycle events:
- created, updated, owner assigned, status changed, archived, reopened, metadata updated, task attach/detach

Migration risks:
- live schema must include migrated columns
- owner semantics and room binding are product-specific
- status rules drive dashboard and project executive flows

### `guardian_spine_project_events`

Belongs in: LIMA core store

Fields:
- `event_id` PK
- `project_id`
- `event_type`
- `occurred_at`
- `room_id` migrated
- `subsystem`
- `source_kind`
- `source_ref`
- `payload_json`

Relationships:
- many project events per project

Lifecycle events:
- project lifecycle audit stream

Migration risks:
- room_id was added later
- project executive and dashboard rely on event consistency

## 4. Event Model

### Task events

Representative event types:
- `task.candidate.created`
- `task.candidate.normalized`
- `task.duplicate.detected`
- `task.created`
- `task.updated`
- `task.completed`
- `task.queued`
- `task.assigned`
- `task.reopened`
- `task.blocked`
- `task.progress`
- `task.project_attached`
- `task.project_detached`

Producer:
- `spine.capture_message()`
- `spine.ingest_subsystem_event()`
- `spine.sync_chat_task_created()`
- `spine.sync_chat_task_status()`
- `spine.emit_task_master_action()`
- `spine.ingest_task_guardian_result()`

Consumer:
- queue derivation helpers
- task master adapter
- room and operator routes
- dashboard task views

Required fields:
- `event_type`, `subsystem`, `source_kind`, `source_ref`, `correlation_id`
- task payload with `title`, `status`, `type`, `priority`, `owner_kind`, `confidence`

Sensitive fields:
- `payload_json` may contain excerpts and tool outputs
- `source_excerpt`

Redaction requirements:
- preserve no-secret guarantee for tool-derived outputs
- avoid leaking vault contents or approval tool args into task payloads

Ownership:
- generic event envelope in LIMA core
- Sparkbot-specific task derivation heuristics and chat-task mirror linkage in adapters

### Approval events

Representative event types:
- `approval.required`
- `approval.granted`
- `approval.denied`
- `approval.discarded`
- `task.approval.required`
- `task.approval.granted`
- `task.approval.denied`

Producer:
- `pending_approvals.py`
- `spine.emit_approval_event()`

Consumer:
- approval-waiting queue
- blocked queue
- operator dashboard
- approval history readers

Required fields:
- `tool_name`
- `confirm_id`
- `approval_state`
- optional `task_id`

Sensitive fields:
- approval `tool_args`
- any secret-like parameters

Redaction requirements:
- tool args must remain redacted in emitted events
- original args may remain in pending approval storage, not in Spine payloads

Ownership:
- generic approval event envelope and approval-state mirror in LIMA core
- Sparkbot-specific task-target inference and UX coupling in adapter

### Memory events

Representative event types:
- `memory.signal`
- memory-derived subsystem events that reopen or create tasks

Producer:
- `spine.ingest_memory_signal()`
- `memory.py` via `spine.ingest_subsystem_event()`

Consumer:
- resurfaced queue
- stale/resurfaced follow-up signals
- event stream

Required fields:
- signal text/content
- `source_kind=memory`
- optional `reopen_task_id`

Sensitive fields:
- memory facts
- user/profile data

Redaction requirements:
- block secret-like facts from being emitted
- preserve existing memory PII safeguards before any extraction

Ownership:
- generic event envelope in LIMA core
- Sparkbot-specific memory semantics, fact classification, and reopen heuristics in adapter

### Meeting events

Representative event types:
- `meeting.note.created`
- `meeting.summary.created`
- `meeting.decisions.created`
- `meeting.action_items.created`
- `meeting.output.created`

Producer:
- `crud.create_chat_meeting_artifact()`
- `spine.capture_meeting_artifact()`
- `spine.emit_meeting_output_event()`

Consumer:
- event stream
- task/project derivation
- markdown meeting mirrors

Required fields:
- artifact type/id
- room id
- content markdown or excerpt

Sensitive fields:
- meeting notes can contain confidential discussion

Redaction requirements:
- redact secrets before event payload storage if meeting notes include them
- preserve excerpt truncation behavior

Ownership:
- generic meeting event models in LIMA core
- Sparkbot room/artifact linkage and mirror file generation in adapter

### Project events

Representative event types:
- `project.created`
- `project.updated`
- `project.owner_assigned`
- `project.archived`
- `project.active`
- `project.metadata_updated`
- `project.task_attached`
- `project.task_detached`

Producer:
- `project_executive.py`
- `spine.emit_project_lifecycle_event()`
- `spine.update_project_owner()`
- `spine.update_project_status_canonical()`
- `spine.update_project_metadata()`

Consumer:
- project event readers
- project workload summaries
- operator project management UI

Required fields:
- `project_id`
- project display/status metadata
- actor/source metadata

Sensitive fields:
- project summaries may reference internal work

Redaction requirements:
- apply same no-secret rule to project metadata if sourced from tool outputs

Ownership:
- generic project event/store models in LIMA core
- Sparkbot-specific room ownership semantics and UI flows in adapter

### Breakglass/security events

Representative event types:
- `breakglass.requested`
- `breakglass.opened`
- `breakglass.closed`

Producer:
- `rooms.py` via `spine.emit_breakglass_event()`
- approval subsystem

Consumer:
- security audit stream
- operator dashboard
- potential future alerts

Required fields:
- room id
- actor id
- event type

Sensitive fields:
- confirm ids
- any auth/session metadata

Redaction requirements:
- never log PIN values
- do not emit secret-bearing approval context

Ownership:
- generic security event envelope in LIMA core
- Sparkbot-specific breakglass flow integration in adapter

### Verifier events

Current state:
- verifier results affect Task Guardian and executive flows but do not appear as a standalone Spine subsystem today
- verifier state is encoded into `task_guardian` payloads such as `verification_status`, `recommended_next_action`, and output excerpts

Producer:
- `task_guardian.py` via `spine.ingest_task_guardian_result()`

Consumer:
- queue state transitions
- operator dashboards

Required fields:
- verification status
- summary
- recommended next action

Sensitive fields:
- output excerpts can contain secrets if not masked upstream

Redaction requirements:
- preserve secret masking before verifier excerpts enter Spine

Ownership:
- generic verification result fields in LIMA core event models
- Sparkbot-specific verifier/tool semantics remain adapter-owned

### Scheduled job events

Representative event types:
- `task.progress`
- `task.blocked`
- `task.completed`
- `handoff.created`
- `worker.status`
- `room.created`
- `room.updated`

Producer:
- `task_guardian.py`
- `meeting_heartbeat.py` through `crud.py` and meeting artifacts
- room lifecycle via `crud.py`
- worker flows via `spine.emit_worker_status_event()`

Consumer:
- queue derivation
- cross-room event feed
- operator dashboard

Required fields:
- job/source identifiers
- room id
- output summary or status text

Sensitive fields:
- excerpts from job outputs

Redaction requirements:
- prevent scheduled jobs from emitting secrets into `payload_json`

Ownership:
- generic event envelopes in LIMA core
- Sparkbot-specific job schedulers and room/worker semantics in adapters

## 5. Adapter Boundaries

### `SpineStore`

Purpose:
- canonical persistence boundary for Spine entities

Methods:
- `init_schema()`
- `list_tasks(filters)`
- `get_task(task_id)`
- `upsert_task(task_model)`
- `append_event(event_model)`
- `list_events(filters)`
- `upsert_project(project_model)`
- `list_projects(filters)`
- `append_project_event(project_event_model)`
- `record_link(link_model)`
- `record_assignment(assignment_model)`
- `record_approval(approval_model)`
- `record_handoff(handoff_model)`

LIMA-generic parts:
- entity models, serialization, schema management

Sparkbot-specific parts:
- none, except any migration of existing on-disk file locations

### `SpineEventBus`

Purpose:
- ingestion and fan-out boundary for subsystem events

Methods:
- `ingest(event)`
- `register_producer(registration)`
- `list_producers()`
- `emit_approval_event(...)`
- `emit_breakglass_event(...)`
- `emit_worker_status_event(...)`

LIMA-generic parts:
- event envelope and producer registry

Sparkbot-specific parts:
- task-target inference for approvals
- room-specific source conventions

### `TaskAdapter`

Purpose:
- isolate Sparkbot `ChatTask` sync and task-master round-trip logic

Methods:
- `sync_chat_task_created(task, session)`
- `sync_chat_task_status(task, status, session)`
- `emit_task_master_action(task, action, actor_id, payload, session)`
- `get_task_by_chat_task_id(chat_task_id)`

LIMA-generic parts:
- task lifecycle command/result models

Sparkbot-specific parts:
- `ChatTask`, `TaskStatus`, `sqlmodel.Session`, room/task ORM persistence

### `ProjectAdapter`

Purpose:
- isolate Sparkbot explicit project lifecycle management from core storage

Methods:
- `create_project(input, actor_id, source_ref)`
- `update_metadata(project_id, fields, actor_id, source_ref)`
- `update_owner(project_id, owner_kind, owner_id, actor_id, source_ref)`
- `transition_status(project_id, new_status, actor_id, source_ref, reason)`
- `attach_task(project_id, task_id, actor_id, source_ref)`
- `detach_task(project_id, task_id, actor_id, source_ref)`

LIMA-generic parts:
- project command and event models

Sparkbot-specific parts:
- room/project coupling, owner semantics, forced archive guards, UI messaging

### `ApprovalAdapter`

Purpose:
- connect generic pending approval core to Spine task/project state

Methods:
- `find_target_task(room_id, tool_name, event_type)`
- `mirror_approval_state(confirm_id, tool_name, state, payload)`
- `expire_pending(confirm_id)`

LIMA-generic parts:
- approval event models, approval history persistence

Sparkbot-specific parts:
- task lookup heuristics, breakglass and operator UX assumptions

### `MemoryAdapter`

Purpose:
- isolate memory-derived signals and reopen semantics

Methods:
- `emit_memory_signal(signal_text, room_id, reopen_task_id)`
- `derive_memory_event_payload(memory_event)`
- `validate_memory_redaction(memory_event)`

LIMA-generic parts:
- memory signal event model

Sparkbot-specific parts:
- memory taxonomy, lifecycle states, fact promotion rules, user/profile shape

### `MeetingAdapter`

Purpose:
- isolate meeting artifacts and markdown mirror behavior

Methods:
- `capture_meeting_artifact(artifact, session)`
- `emit_meeting_output(room_id, artifact_type, artifact_id, content, actor_id)`
- `write_meeting_mirror(event)`

LIMA-generic parts:
- meeting event envelope

Sparkbot-specific parts:
- `ChatMeetingArtifact`, room naming, markdown mirror layout, action-item promotion rules

### `SecurityEventAdapter`

Purpose:
- isolate breakglass and security audit integration

Methods:
- `emit_breakglass(room_id, user_id, event_type, payload)`
- `emit_security_event(event)`
- `redact_security_payload(payload)`

LIMA-generic parts:
- security event envelope

Sparkbot-specific parts:
- breakglass flow, room route triggers, operator identity semantics

### `DashboardAdapter`

Purpose:
- keep the current route and frontend response contract outside the core Spine package

Methods:
- `get_room_overview(room_id)`
- `get_operator_queue(queue_name, limit)`
- `get_task_detail(task_id)`
- `get_project_workload()`
- `format_response(model)`

LIMA-generic parts:
- none; this is an adapter layer

Sparkbot-specific parts:
- FastAPI response models, queue naming, operator auth, React data contract

## 6. Extraction Phases

### PR 4A: introduce Spine interfaces only

Scope:
- add `SpineStore`, `SpineEventBus`, and adapter interface definitions to `lima_guardian`
- add shared Spine entity models and type contracts
- no runtime adoption

Why first:
- lowest-risk seam-setting
- no data movement
- creates target contracts for later PRs

### PR 4B: standalone event models

Scope:
- move generic Spine event/task/project/link/approval/handoff dataclasses and request models into `lima_guardian`
- no storage yet

Why:
- isolates core schema vocabulary before moving persistence

### PR 4C: standalone SQLite `SpineStore`

Scope:
- move generic SQLite schema management and CRUD into `lima_guardian`
- include migrated live schema, not just original DDL
- no Sparkbot ORM sync
- keep the standalone schema generic; Sparkbot live-schema mapping still must be validated separately against `_ensure_schema_migrations()`

Why:
- separates persistence from Sparkbot adapters

### PR 4D: Sparkbot adapter shim

Scope:
- add Sparkbot-side adapters for `ChatTask`, room lifecycle, approvals, meeting artifacts, and dashboard calls
- existing behavior continues to call old functions internally

Why:
- keeps runtime stable while adapters are introduced

### PR 4E: Task/Project lineage migration

Scope:
- move task-master and project-executive lineage logic to the new interfaces
- keep Sparkbot-specific `ChatTask` sync in adapters

Why:
- this is the highest-value, highest-coupling mid-phase move

### PR 4F: dashboard/API adapter split

Scope:
- move FastAPI response shaping and React assumptions out of core storage logic
- routes consume adapter layer rather than raw Spine functions

Why:
- prevents the LIMA core from inheriting Sparkbot route/UI coupling

### PR 4G: Sparkbot consumes LIMA Spine package

Scope:
- switch Sparkbot imports from inline `guardian/spine.py` internals to `lima_guardian` Spine package plus adapters
- delete nothing until all tests and migration dry-runs are green

Why:
- final adoption step only after parity is proven

## 7. Risk Register

| Risk | Severity | Files affected | Mitigation | Tests needed | Rollback plan |
| --- | --- | --- | --- | --- | --- |
| Data loss in Spine SQLite migration | Critical | `spine.py`, future `SpineStore`, `spine.db` | freeze schema contract, snapshot DB, dry-run migrator on copied DB, never mutate production file in first extraction PRs | migration fixture tests, row-count parity, field-level diff | revert to inline `spine.py`, restore copied DB snapshot |
| Migrated columns omitted from new schema | High | `spine.py`, future `SpineStore` | model live schema from dataclasses plus `_ensure_schema_migrations()` output | schema introspection tests, read/write round-trip tests | keep Sparkbot on old store, discard new schema |
| Event redaction regression | Critical | `pending_approvals.py`, `vault.py`, `memory.py`, `executive.py`, future event bus | centralize redaction helpers, add no-secret payload assertions | approval redaction, vault event, executive redaction, memory secret-block tests | route event emission back to current Sparkbot paths only |
| Approval bypass via broken task-target inference | Critical | `spine.py`, `pending_approvals.py`, future `ApprovalAdapter` | keep inference adapter-side, mirror existing tests, require explicit confirm-state transitions | approval required/granted/denied/discarded lineage tests | revert to current inline approval integration |
| Duplicate background job writes | High | `task_guardian.py`, `meeting_heartbeat.py`, `crud.py`, future adapters | do not switch producers until adapters are exclusive; feature-flag any dual registration | scheduler integration tests, event count uniqueness tests | disable new adapter path and return to current emitters |
| Dashboard response mismatch | High | route `chat/spine.py`, `frontend/src/lib/spine.ts`, `frontend/src/routes/_layout/spine.tsx` | freeze current response contract behind `DashboardAdapter` | API contract tests, UI smoke checks | keep routes on existing inline Spine readers |
| Broken Task Guardian integration | High | `task_guardian.py`, `task_master_adapter.py`, `spine.py` | separate generic event store from Sparkbot task/job semantics | scheduled run -> queue transition tests | revert task guardian emitter path |
| Broken Project Executive integration | High | `project_executive.py`, `spine.py`, routes | move project mutation APIs only after interfaces and store are proven | project lifecycle tests, owner/status/attach/detach tests | revert project adapter calls to inline Spine |
| Memory write regression or bad reopen logic | High | `memory.py`, `spine.py`, future `MemoryAdapter` | keep memory semantics in Sparkbot adapter; only move generic event model first | memory resurfacing tests, orphan/resurfaced queue tests | revert memory signal path |
| Mirror file drift or accidental reverse dependency | Medium | `spine.py` mirror helpers, markdown artifacts | keep mirror generation adapter-side, forbid mirror -> canonical reads | mirror existence/parity tests | disable new mirror writer, keep old inline writer |

## 8. Acceptance Gates Before Extraction

Before any actual Spine extraction starts:

- standalone `lima_guardian` tests still pass
- Sparkbot guardian tests still pass
- `backend/tests/services/test_guardian_spine.py` passes
- project executive tests pass
- Spine event redaction tests pass
- approval and breakglass tests pass
- migration dry-run against copied `spine.db` succeeds with parity checks
- dashboard continues reading the same response shapes
- no duplicate background job event emission
- no secret leakage in `payload_json`, mirrors, or queue APIs

Recommended concrete gate commands:

- `pytest -q tests/test_lima_guardian_vault_auth.py tests/test_lima_guardian_pending_policy.py tests/test_lima_guardian_token_verifier_improvement.py`
- Sparkbot guardian service tests
- Sparkbot `test_guardian_spine.py`
- Sparkbot `test_project_executive.py`
- redaction/security test suite for approvals, executive, vault, memory

## 9. Recommended First Spine PR

Recommended next PR after this planning report:

### PR 4A: introduce Spine interfaces only

Scope:
- add `lima_guardian.spine_models` and `lima_guardian.spine_interfaces`
- define `SpineStore`, `SpineEventBus`, `TaskAdapter`, `ProjectAdapter`, `ApprovalAdapter`, `MemoryAdapter`, `MeetingAdapter`, `SecurityEventAdapter`, `DashboardAdapter`
- copy no runtime logic from Sparkbot yet
- add interface-focused tests only

Why this is the smallest safe next PR:
- no production behavior change
- no DB migration
- no event-path switch
- no ORM coupling
- gives later PRs a stable contract to target

Non-goals for that PR:
- no SQLite SpineStore implementation yet
- no route rewiring
- no dashboard changes
- no `ChatTask` sync migration

## Spine Boundary Summary

The clean boundary is:

- LIMA core owns event/task/project/link/approval/handoff models, generic SQLite persistence, producer registry, and generic queue/query semantics.
- Sparkbot adapters own `ChatTask` sync, room/project ownership semantics, approval target inference, memory-specific reopening logic, meeting artifact integration, breakglass route integration, and the FastAPI/React response contract.

If that separation is not maintained, the extraction will simply recreate `spine.py` in a new repo and keep the same coupling.
