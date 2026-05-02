# Memory_Guardian

## Repo URL

- https://github.com/armpit-symphony/Memory_Guardian

## Original Purpose

Memory Guardian, branded there as Memory OS MVP, was a durable memory subsystem for autonomous agents. It provided append-only storage, full-text retrieval, consolidation, and token-bounded context packing intended for safe LLM injection.

## Useful Concepts To Remember

- Use an append-only ledger as the memory source of truth.
- Keep retrieval read-only from the model's perspective.
- Separate storage, indexing, consolidation, retrieval, and context packing responsibilities.
- Enforce token budgets before memory enters prompts.
- Scope recall narrowly by default and avoid letting memory become an implicit execution channel.

## What NOT To Copy Directly

- The legacy `memory_os` implementation, schemas, sqlite indexes, or file-first storage format.
- The original CLI flows and on-disk data layout.
- Any direct assumptions about OpenClaw session identifiers or filesystem paths.
- Generated package metadata or stored data artifacts from the original repo.

## Possible Future LIMA Ideas

- A LIMA memory service with durable provenance and stronger isolation boundaries.
- Hybrid retrieval that can evolve beyond file-first indexing while preserving auditability.
- Consolidation pipelines that separate durable facts from transient conversational context.
- Memory safety rules that explicitly prevent instruction injection through recalled content.

## Current LIMA Replacement/Status

- In this repository, the closest extracted implementation is `app/services/guardian/memory.py` together with the vendored `app/services/guardian/memory_os/` package and the simplified wrapper in `guardian/memory.py`.
- Status: historical reference only. The original standalone Memory_Guardian repo should inform redesign, not be copied back in.
