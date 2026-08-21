---
name: codex-contract-delivery
description: Use when delivering a Codex change through governed requirements, design, package planning, verification, release, incident response, or workflow evolution.
---

# Codex Contract Delivery

Run `scripts/status --json` first. Treat its trusted phase as authoritative; do not infer phase from prose. Load only the skill or reference for that phase.

| Phase | Route |
| --- | --- |
| 0 — discover actual state | CodeGraph-first repository and runtime inspection |
| 1 — requirements/domain | `grill-with-docs`, `domain-modeling`, `superpowers:brainstorming` |
| 2 — Penpot interaction | Actual Penpot foundations, components, flows, states, breakpoints, accessibility, error, and permission states |
| 3 — sufficient system design | Hard-to-reverse boundaries and delivery constraints only |
| 4 — modules/submodules | Business capability and data ownership; independently understandable/testable in one-agent context |
| 5 — package planning | `superpowers:writing-plans` |
| 6 — implementation/unit | Package-level `superpowers:subagent-driven-development` with TDD |
| 7 — contract/integration verification | Applicable unit, repository, migration, API-event, consumer-provider, cross-module, real-middleware, browser, security, performance, accessibility, and recovery tests |
| 8 — TEST release | One build artifact; isolated TEST; migrations, smoke, critical journeys, observability, and rollback rehearsal |
| 9 — PROD/online regression | Release Manifest, backup/restore, canary or blue-green, abort thresholds, probes, rollback, and explicit operation authorization |
| 10 — incident/defect | Contain reversibly, then `superpowers:systematic-debugging`; after three failed corrections, perform architectural diagnosis and return to a Safe Checkpoint |

## Human Gates

1. Gate 1: approve the requirements baseline after Phase 1.
2. Gate 2: approve the integrated Penpot and technical design after Phase 4.
3. Gate 3: approve package scope, dependencies, tasks, risks, completion evidence, and release strategy after Phase 5.
4. Gate 4: accept the verified result after applicable product online regression or Workflow Release canary monitoring window after Phase 9. Production/high-risk infrastructure additionally requires explicit operation authorization.

## Hard Stops

Stop immediately when any of these is true:

1. A material business or L2 change requires human decision.
2. The Effective Contract contains an unresolved conflict.
3. A check required by the Effective Contract, Package Verify, or Release Verify fails, regardless of incident severity.
4. A P0/P1 migration, environment, runtime, or release-safety failure exists.
5. Production or high-risk infrastructure authorization is absent.
6. A token/review/correction stop-loss is reached after returning to a Safe Checkpoint.
7. Trusted run state, transactional history, pinned Workflow Release, approval/evidence provenance, or evaluator isolation cannot be established.
8. An Evolution Candidate attempts to modify the Trusted Workflow Core, access a protected holdout, exceed its query budget, widen beyond evaluated scope, or promote without bound evidence and trusted approval.
