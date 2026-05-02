# Sparkbot Serializer Fixture Comparison

Date: 2026-05-02
Status: Tiny copied-data-only fixture comparison
Target branch: `pr4j-serializer-fixture-comparison`

## Purpose

This step compares a very small set of sanitized expected serializer fixtures to LIMA-generated route-shaped envelopes on copied temp data.

The goal is not full serializer equivalence. It is to prove that one queue serializer shape and one task-detail serializer shape can be normalized and matched safely without importing Sparkbot runtime code.

## Safety model

- source DB is treated as read-only
- the DB is copied to a temp location first
- all reads happen against the temp copy
- no Sparkbot imports are used
- no FastAPI route code is modified
- no React/dashboard code is modified
- no live DB writes occur

## Covered fixtures

- `open_queue.json`
- `task_detail.json`

## Normalization rules

- volatile IDs normalize to `<id>`
- volatile timestamps normalize to `<timestamp>`
- source references normalize to `<ref>`
- fixture comparison treats fixtures as the expected subset
- comparison checks normalized structure and stable values, not live-generated IDs or timestamps

## Limitations

- only two serializer shapes are covered
- this does not validate HTTP transport details, auth, or registration
- this does not validate every field on every route
- fixture comparison is structural and sanitized, not a production-response byte-for-byte diff

## Pass/fail criteria

The comparison passes only if:

- the source DB exists
- temp copy is used
- normalized `open_queue` matches its fixture
- normalized `task_detail` matches its fixture
- no raw secret-like values appear in the JSON report

## Next step after passing

The next safe PR is one or two more serializer fixtures for adjacent Spine routes, still copied-data only and still without runtime wiring.
