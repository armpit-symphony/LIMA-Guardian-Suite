# Sparkbot Field-Level Parity

Date: 2026-05-02
Status: Field-level parity checks on copied data only
Target branch: `pr4i-field-level-route-serializer-parity`

## Purpose

This step validates a small subset of field-level route serializer compatibility between Sparkbot-shaped envelopes and LIMA-produced route-shaped output.

It is intentionally narrower than full serializer parity. The goal is to check that the most important queue, event, and detail item fields exist with compatible basic types and preserved redaction markers.

## Safety model

- source DB is treated as read-only
- the source DB is copied to a temp location first
- only the temp copy is read
- no Sparkbot imports are used
- no FastAPI routes are modified
- no React/dashboard code is modified
- no live DB writes occur

## Covered route fields

Current covered item contracts:

- open queue item
- blocked queue item
- approval-waiting item
- recent event item
- task detail envelope

Checks include:

- required field names
- basic type compatibility
- nullable field allowance
- redaction marker preservation for recent event payloads

## Intentionally uncovered fields

- room overview field-by-field parity
- project workload field-by-field parity
- approval and handoff object contents
- auth, route registration, HTTP status codes, and transport concerns
- full serializer equivalence for every Sparkbot endpoint

## Limitations

- item contracts are based on the copied-data route-shape layer, not live Sparkbot imports
- type checks are basic and do not validate semantic value ranges
- recent event redaction is checked on the sampled serialized event payload only

## Pass/fail criteria

The checks pass only if:

- the source DB exists
- temp copy is used
- each covered contract validates successfully
- redaction markers remain present where secret-like fields exist
- no raw secret-like values are emitted in the JSON report

## Next step after passing

The next safe PR is an expanded serializer parity fixture set for one or two concrete Sparkbot route handlers, still copied-data only and still without runtime wiring.
