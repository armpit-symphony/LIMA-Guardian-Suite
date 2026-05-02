# Sparkbot Route-Shape Parity

Date: 2026-05-02
Status: Test-only route-shape parity checks
Target branch: `pr4h-route-shape-parity-checks`

## Purpose

This step compares selected Sparkbot API envelope shapes to read-only adapter output on copied temp data only. It does not attempt runtime route replacement.

The goal is narrower than full behavior parity:

- prove the read-only adapter can format Sparkbot-like envelopes
- validate the required top-level keys for selected route shapes
- ensure redacted event payloads stay redacted in serialized route outputs

## Safety model

- source DB is treated as read-only
- the DB is copied to a temp location first
- all reads happen against the temp copy
- no Sparkbot imports are used
- no FastAPI route code is modified
- no React/dashboard code is modified
- no live DB writes occur

## Supported route envelopes

Current route-shaped outputs:

- open queue
- blocked queue
- approval-waiting queue
- recent events
- room overview
- project workload
- task detail with lineage

## Limitations

- only required top-level keys are validated
- approvals and handoffs remain empty arrays in task detail
- this does not validate HTTP status codes, auth, or route registration
- this does not yet compare every field to Sparkbot route serializers

## Pass/fail criteria

The checks pass only if:

- the source DB exists
- temp copy is used
- each supported envelope contains the required top-level keys
- redacted payload fields remain redacted
- no raw secret-like values appear in the JSON report

## Next step after passing

The next safe PR is a field-level parity comparison for a small subset of route serializers using copied data and explicit fixture expectations, still without any runtime wiring.
