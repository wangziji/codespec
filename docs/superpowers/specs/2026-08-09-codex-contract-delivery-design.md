# Codex Contract Delivery Design

**Status:** Approved design direction; written specification pending final user review

**Date:** 2026-08-09

**Scope:** A reusable Codex workflow and project template for large greenfield and brownfield software projects
**Reference project:** TradeWise, excluding its existing `spec-workflow` and `codex-openspec-superpowers-github` workflow designs

## 1. Decision Summary

The workflow uses a **Lean Contract Spine** rather than a hierarchy of duplicated specifications.

The approved first-round decisions are:

1. Deliver a reusable global Codex Skill, project template, and deterministic CI validators.
2. Keep product and technical contracts in the repository, intended visual design in Penpot, and queue/status coordination in GitHub.
3. Use four human review types: requirements baseline, integrated design, delivery plan, and result acceptance.
4. Allow automatic TEST deployment and regression; require explicit authorization before production or high-risk infrastructure operations.
5. Budget work per Delivery Package with model routing, measured cost, and safe stop-loss behavior.
6. Use CodeGraph before broad code reading for symbol, relationship, impact, and affected-test retrieval.

The design deliberately rejects a full custom specification platform. It does not build a graph database, a general semantic reasoner, multi-parent specification inheritance, or gates based on narrative agent transcripts.

## 2. Problem Statement

The replacement workflow must correct these observed failure modes:

- large token expenditure without completing a concrete business outcome;
- many documents and gates that contradict one another;
- frontend work using fixtures while backend APIs or tables do not exist;
- design, API, persistence, tests, and deployment evolving independently;
- architecture decisions deferred until implementation is already constrained;
- historical green checks treated as proof of current runtime correctness;
- deployment blocked by topology, migration, tool-version, or credential realities discovered too late;
- reviewers expanding scope beyond the approved requirement;
- repeated full-context agent and review passes.

## 3. Goals

The workflow shall let Codex carry work through:

1. requirements and domain design;
2. Penpot interaction and visual design;
3. whole-system technical design;
4. module and submodule boundaries;
5. implementation planning;
6. code and unit tests;
7. API, contract, integration, and end-to-end tests;
8. isolated TEST deployment and regression;
9. authorized production release and online regression;
10. incident containment, root-cause diagnosis, and verified correction.

The human shall only need to:

- clarify business decisions that cannot be discovered from evidence;
- approve requirements, integrated design, and Delivery Package plans;
- authorize production or high-risk infrastructure operations;
- accept results.

## 4. Non-Goals

Version 1 will not:

- replace GitHub, Penpot, OpenAPI, AsyncAPI, JSON Schema, CI, or deployment platforms;
- infer business semantics perfectly from natural language or source code;
- guarantee that no semantic goal drift can ever occur;
- retrofit every untouched legacy file before brownfield delivery can continue;
- provide a multi-repository federation control plane;
- require every low-risk change to use an independent frontier-model reviewer;
- treat the existence of a trace link as proof that behavior is correct.

## 5. Governing Principles

The workflow operationalizes the four Karpathy-inspired principles:

### 5.1 Think Before Coding

- Surface material assumptions before implementation.
- Batch unresolved business decisions for the human.
- Present real alternatives and trade-offs.
- Stop on ambiguity that changes observable behavior, authority, data meaning, compatibility, or production risk.

### 5.2 Simplicity First

- Store each constraint once.
- Prefer established contract standards over custom schemas.
- Prohibit speculative modules, abstractions, configuration, and future-proofing.
- Start with a walking skeleton through real UI, API, storage, TEST, and evidence paths.

### 5.3 Surgical Changes

- Every changed line must relate to the active Delivery Package or an explicitly approved prerequisite.
- Unrelated cleanup is reported, not performed.
- Impact analysis determines the smallest safe test and review scope.

### 5.4 Goal-Driven Execution

- Every Requirement Scenario has observable success criteria.
- Every task names a verification step.
- Codex loops until the criteria pass, a safe blocker occurs, or a stop-loss reaches a Safe Checkpoint.

## 6. Authority Model

There is no single universal source of truth. Authority depends on the question:

| Question | Authority |
|---|---|
| Desired product behavior | Approved Project Baseline and Requirement Scenarios |
| Intended visual experience | Approved Penpot revision |
| Intended interfaces and data | Repository contracts |
| Current implementation | Source code at the referenced commit |
| Current deployed behavior | Runtime observation and immutable deployment evidence |
| Work queue and discussion status | GitHub Project, Issues, and Pull Requests |

When authorities disagree, the workflow reports drift. Actual runtime behavior never silently rewrites approved intent, and approved intent never substitutes for proof of actual runtime behavior.

## 7. Minimal Canonical Artifacts

```text
project/
├── AGENTS.md
├── PRODUCT.md
├── CONTEXT.md
├── CONTEXT-MAP.md                 # only for multiple domain contexts
├── architecture/
│   ├── system.md
│   ├── modules/
│   └── adr/
├── contracts/
│   ├── api/
│   ├── events/
│   ├── data/
│   ├── environments/
│   └── penpot-index.yaml
├── deliveries/
│   └── <delivery-id>/
│       ├── contract.yaml
│       └── plan.md
├── workflow/
│   ├── policy.yaml
│   ├── model-policy.yaml
│   └── schemas/
└── .github/workflows/
```

Canonical project files are sharded by stable module or record ID as they grow. Aggregate views, trace matrices, workflow status, budgets, and evidence summaries are generated. Generated views are not separately edited.

## 8. Lean Contract Spine

Each Requirement Scenario connects the minimum evidence needed to reason across layers:

```text
Project Goal
  -> Requirement Scenario
     -> Penpot frame/state, when UI applies
     -> API/event contract, when integration applies
     -> domain/data owner and migration, when persistence applies
     -> Delivery Package
     -> executable verification
     -> TEST/PROD Evidence Attestation
```

The spine is not a graph database. It is a deterministic index generated from repository contracts, Penpot references, test metadata, and release attestations.

### 8.1 Resolution Rules

- A Delivery Contract pins exactly one `base_revision` of the Project Baseline.
- Version 1 permits one baseline plus one package delta; it does not support multi-parent inheritance.
- A child cannot weaken or delete a baseline constraint.
- Explicit conflicts fail resolution; no last-write-wins behavior is allowed.
- Requirement IDs are immutable and never reused.
- Semantic changes create a new revision or a superseding ID with a tombstone link.
- The generated effective view explains the origin of every constraint.

### 8.2 Check Classes

Every validator labels its evidence:

| Class | Meaning |
|---|---|
| Structural | IDs, schemas, revisions, and required links are present |
| Semantic | contracts, types, ownership, and declared behavior are compatible |
| Runtime | the real service, data, identity, environment, or user journey was exercised |

Structural success never claims runtime correctness.

## 9. Change and Approval Model

### 9.1 Change Levels

- **L0:** internal implementation that preserves observable behavior and contracts;
- **L1:** design detail inside approved behavior, with no change to external semantics or risk;
- **L2:** goals, acceptance behavior, authorization, data meaning, external compatibility, environment topology, or production risk.

The affected contract-node type determines the minimum level. Agents do not freely downgrade changes. Ambiguity defaults to L2. Cumulative L1 changes that alter observable behavior become L2.

### 9.2 Approval Binding

An approval records:

- actor and approval role;
- timestamp and decision;
- Project Baseline hash;
- Effective Contract hash;
- Penpot revision, when applicable;
- plan hash, for plan approval;
- Release Manifest digest, for production authorization.

Relevant changes invalidate the approval automatically. Repository-local `approved: true` flags are insufficient. GitHub protected reviews or an equivalent trusted approval system provide the durable record. One human may hold all approval roles, but an agent cannot approve its own artifact.

### 9.3 Iteration

The lifecycle permits backward transitions. A changed canonical node invalidates only approvals and evidence that depend on it. The tool reports the invalidated section by hash rather than restarting the entire workflow.

## 10. Delivery Package Types

| Type | Purpose | UI trace required |
|---|---|---|
| `feature` | user-visible vertical capability | when UI applies |
| `enabler` | shared infrastructure or platform capability | no |
| `migration` | data, protocol, or compatibility transition | no |
| `remediation` | security, quality, or bounded technical-debt correction | only if behavior changes |
| `incident` | containment and root-cause correction | only if behavior changes |

Packages declare dependencies as a DAG. Shared-contract changes use optimistic baseline-revision checks and a merge queue. TEST deployments use package-isolated namespaces where practical; otherwise they serialize with verified reset behavior.

## 11. Lifecycle and Human Gates

### Phase 0: Discover Actual State

Codex inspects the current repository, CodeGraph coverage, code, contracts, CI, migrations, runtime topology, deployment tooling, and live work state. Historical documentation and green checks are routing context, not current proof.

### Phase 1: Requirements and Domain Design

Use `grill-with-docs`, `domain-modeling`, and `superpowers:brainstorming` to establish users, goals, measurable outcomes, domain language, normal and exceptional scenarios, quality attributes, scope, and exclusions.

**Human Gate 1:** approve the requirements baseline.

### Phase 2: Penpot Interaction Design

For UI-impacting work, create or update actual Penpot foundations, components, flows, states, responsive breakpoints, accessibility behavior, and error/permission states. Repository artifacts point to Penpot; they do not replace it.

### Phase 3: Minimum Sufficient System Design

Design only hard-to-reverse boundaries and delivery constraints:

- domain contexts and data ownership;
- security and session model;
- external interfaces and failure semantics;
- TEST/PROD topology;
- migrations and compatibility;
- observability, rollback, and critical quality attributes.

Reversible internal details remain inside Delivery Packages.

### Phase 4: Modules and Submodules

Modules follow business capability and data ownership, not frontend/backend layers. A submodule exists only when it has a clear interface, can be understood and tested independently, and fits one agent's useful context.

**Human Gate 2:** approve the integrated Penpot and technical design.

### Phase 5: Package Planning

Use `superpowers:writing-plans` to plan one bounded Delivery Package. Small test steps remain inside the plan; they do not each receive a fresh agent or full review.

**Human Gate 3:** approve package scope, dependencies, tasks, risks, completion evidence, and release strategy.

### Phase 6: Implementation and Unit Tests

Use package-level `superpowers:subagent-driven-development` with TDD. The default package has one implementation agent, focused tests, coherent commits, and risk-based independent review.

### Phase 7: Contract and Integration Verification

Run the applicable layers:

1. unit tests;
2. repository and migration tests;
3. API/event schema and compatibility tests;
4. consumer/provider contract tests;
5. cross-module integration tests;
6. real middleware tests;
7. browser E2E;
8. security, performance, accessibility, and recovery tests required by risk.

Test traceability requires executable assertions and applicable negative cases. A requirement tag on an empty, skipped, or over-mocked test is not evidence.

### Phase 8: TEST Release

Build the release candidate once, deploy it to isolated TEST, run migrations, smoke tests, critical journeys, observability checks, and rollback rehearsal. Record fidelity gaps that TEST cannot reproduce.

### Phase 9: Production Release and Online Regression

Prepare a signed Release Manifest, verified backup/restore path, canary or blue-green strategy, abort thresholds, safe synthetic probes, and executable rollback before requesting production authorization. Online regression confirms the release; production is not the first safety test.

**Human Gate 4:** accept the verified result after online regression. Production and high-risk infrastructure changes additionally require explicit operation authorization.

### Phase 10: Incident and Defect Handling

Contain damage first through a reversible rollback, traffic stop, or safe feature disable when necessary. Then use `superpowers:systematic-debugging` to reproduce, trace data flow, compare working patterns, test one hypothesis, write a failing test, correct the root cause, and re-run relevant release evidence. Three failed correction attempts trigger architectural review.

## 12. Penpot Contract

Penpot is authoritative for intended visual and interaction design. The deployed application is authoritative for actual behavior. A mismatch is a defect.

Each UI-impacting package pins:

- Penpot project, file, page, and frame identifiers, plus an approval revision identifier when Penpot exposes one or an immutable approval-snapshot hash otherwise;
- related Requirement Scenario IDs;
- route or surface;
- required states, including loading, empty, error, permission, and confirmation where applicable;
- required breakpoints;
- design-token and component dependencies.

An exported snapshot with a hash is retained as approval and disaster-recovery evidence, not as a competing design source. Penpot availability blocks only UI-impacting design work, not unrelated backend or enabler packages.

## 13. Code Retrieval Policy

CodeGraph is the mandatory first-line relationship retrieval tool, not the sole authority.

```text
1. Run codegraph status for freshness and coverage.
2. Run codegraph sync when the index is stale.
3. Use query, callers, callees, impact, and affected for symbols, relationships, change impact, and test routing.
4. Record the graph revision and unsupported surfaces.
5. Verify high-risk findings and negative claims against source code.
6. Use rg for documentation, configuration, exact strings, and graph-unsupported languages or files.
7. Read only the smallest source slices needed to confirm the result.
```

An empty graph result never proves that no caller, dependency, or affected test exists unless coverage for that surface is established.

## 14. Environment Contract

At minimum, projects define:

| Environment | Purpose | Data |
|---|---|---|
| CI Ephemeral | unit, contract, and component integration | generated |
| TEST | API, cross-service, E2E, migration, release, and rollback | isolated test data |
| PROD | formal business operation | real data |

TEST and PROD must not share writable databases, schemas, queues, buckets, SaaS tenants, credentials, or side-effecting external accounts. Isolation is verified through live resource-identity probes, policy-as-code, network boundaries, and write-denial tests, not names alone.

TEST preserves production protocol, authentication path, engine/version class, configuration mechanism, artifact, health checks, migration mechanism, and observability. Differences in scale, quota, entitlements, third-party behavior, and data realism are recorded as fidelity gaps and compensated through canaries and abort thresholds.

Projects may prohibit local middleware in their environment contract. A deployment tool must not invent a topology that contradicts the approved external services.

## 15. Release Manifest and Evidence

The same signed Release Manifest moves from TEST to PROD. It pins:

- application and image digests;
- migration checksums;
- runtime configuration schema/version;
- feature-flag set;
- deployment manifest and sidecar versions;
- infrastructure version;
- contract and Penpot revisions;
- immutable TEST evidence pointers.

Evidence Attestations are created by trusted CI/deployment identities and include environment identity, artifact digest, probe version, timestamp, result, and sanitized logs. Evidence is append-only and retained outside mutable workspace files; the Delivery Package stores stable references.

Migrations default to expand-migrate-contract when rolling compatibility requires it. Alternative strategies are allowed when explicitly justified and proven safe for the project's deployment model.

## 16. Model and Token Policy

### 16.1 Deterministic Tools First

Search, schema validation, compilation, linting, formatting, test execution, contract diffing, environment comparison, and evidence aggregation use tools rather than model narration.

### 16.2 Model Tiers

Actual model identifiers live in a versioned policy:

- **Cheap:** exact mechanical transformations with complete inputs and deterministic verification;
- **Standard:** normal coding, tests, local integration reasoning, and scoped reviews;
- **Frontier:** ambiguous requirements, Penpot experience, architecture, security, irreversible migration, complex debugging, and production risk.

A Cheap task upgrades after its first requirement misunderstanding or before a second correction loop. Routing considers affected contracts and risk, not the task's superficial label.

### 16.3 Package and Review Limits

- Default: one implementer and at most one normal independent reviewer per package.
- Low risk: deterministic verification and sampled independent review.
- Medium risk: one Standard reviewer.
- High risk: one Frontier reviewer; specialized security or migration checks only when applicable.
- One normal correction and scoped re-review; additional work requires a concrete Critical/Important contract violation and controller stop-loss decision.
- Focused tests run during iteration; broad suites run once at the package boundary unless evidence shows a cross-module regression.

### 16.4 Measured Budget

Initial phase percentages are planning heuristics, not claims of savings. The first representative greenfield and brownfield packages establish a baseline for:

- tokens per accepted delivery;
- elapsed time per accepted delivery;
- correction and review rounds;
- escaped defects;
- evidence-generation overhead.

At 70% of the package budget, the controller stops initiating optional work and audits remaining scope, repeated context, package size, environment blockers, and model fit. At 100%, work first reaches or restores a Safe Checkpoint; it never stops mid-migration, mid-deployment, or in an unsafe partial state.

## 17. Brownfield Ratchet

Brownfield adoption begins with a versioned Legacy Baseline. Existing non-conformance becomes a Legacy Exemption with owner, reason, affected surface, risk, expiry, and migration milestone.

- New code follows the current workflow.
- Touched and affected legacy surfaces are brought into compliance as part of the package.
- Untouched legacy code does not require fabricated requirement, Penpot, or data links.
- No new debt may use a legacy exemption.
- Expired high-risk exemptions block release.

## 18. CI Gates

There are three executable gate classes:

### 18.1 Contract Check

Incremental checks cover schema versions, immutable IDs, baseline revisions, approval bindings, contract conflicts, API/schema compatibility, Penpot references, CodeGraph coverage metadata, environment policy, and prohibited production fakes.

### 18.2 Package Verify

Impact analysis selects compilation, lint, unit, migration, contract, integration, browser, security, performance, accessibility, and recovery tests. Full audits may run nightly; ordinary packages avoid full-repository repetition.

### 18.3 Release Verify

The release candidate must pass TEST deployment, migration, smoke, critical journeys, observability, rollback, Release Manifest, evidence-provenance, and live environment-identity checks.

CI never gates on narrative brainstorming logs, agent transcripts, or manually expanded review Markdown.

## 19. Workflow Skill Package

The reusable package is named `codex-contract-delivery`:

```text
codex-contract-delivery/
├── SKILL.md
├── agents/openai.yaml
├── scripts/
│   ├── init
│   ├── doctor
│   ├── status
│   ├── validate
│   ├── trace
│   ├── next
│   ├── budget
│   └── evidence
├── references/
├── schemas/
└── assets/
```

`SKILL.md` remains a short trigger and router. References load by current phase. Repository policy pins compatible schema and validator versions; CI vendors or locks its runtime. Local tooling refuses unknown major schema versions. `doctor` verifies CodeGraph, Penpot capability, GitHub, CI/deployment prerequisites, validator compatibility, and environment access before work begins.

## 20. Hard Stops

Only these conditions stop autonomous progression:

1. a material business or L2 change requires human decision;
2. the Effective Contract contains an unresolved conflict;
3. a P0/P1 verification, migration, environment, or release-safety failure exists;
4. production or high-risk infrastructure authorization is absent;
5. a token/review/correction stop-loss is reached after returning to a Safe Checkpoint.

Other findings are corrected automatically when within scope or recorded as non-blocking evidence.

## 21. Known Disadvantages and Trade-offs

The Lean Contract Spine still has real costs:

- baseline, environment, and Penpot bootstrap work precedes the first feature;
- Penpot and CodeGraph introduce external availability and version dependencies;
- schemas, validators, provenance, and workflow migrations require maintenance;
- structural links can create false confidence if runtime checks are omitted;
- human approvals create queueing latency;
- high-fidelity isolated TEST infrastructure costs money and remains imperfect;
- semantic goal drift can be reduced and surfaced, not mathematically eliminated;
- single-repository version 1 does not solve multi-repository federation;
- high-risk independent review consumes tokens to reduce correlated errors;
- Evidence Attestations may expose sensitive topology unless sanitized and access-controlled;
- a workflow that is applied uniformly to trivial work becomes bureaucracy.

Mitigations are risk-based enforcement, brownfield ratcheting, standard contracts, hash-bound approvals, runtime evidence, package-level context, measured cost, and an explicit refusal to build the deferred full platform.

## 22. Required Behavior Tests for the Workflow

The Skill implementation must prove negative and positive behavior:

- missing required Penpot revision blocks UI implementation;
- an unsupported CodeGraph surface triggers source fallback rather than a false negative;
- frontend use of an undeclared API fails;
- declared persistence without a data owner or applicable migration fails;
- hidden production fake providers are caught by a runtime probe fixture;
- TEST and PROD aliases resolving to one writable resource fail;
- a child package cannot weaken its pinned baseline;
- an L2 node change invalidates approval;
- changed approval-bound content cannot reuse an old approval;
- a changed package fails optimistic baseline-revision validation;
- trivial, skipped, or assertion-free tests do not count as scenario evidence;
- absent trusted TEST evidence blocks production readiness;
- a Release Manifest mismatch blocks promotion;
- Cheap-model repeated misunderstanding upgrades routing;
- reviewer scope expansion does not enter the correction loop;
- a token stop-loss completes or rolls back to a Safe Checkpoint;
- defect correction cannot claim completion without reproduction and root-cause evidence;
- a valid low-risk package can complete without narrative process artifacts;
- a compliant end-to-end package reaches acceptance with immutable evidence.

## 23. Requirement Coverage

| Requested outcome | Design evidence |
|---|---|
| requirements through bug correction | ten-phase lifecycle |
| human only clarifies, reviews, and accepts | four review types plus explicit production authorization |
| low/standard/frontier model allocation | versioned risk-based model policy |
| Penpot implementation | pinned Penpot Design Baseline and UI gate |
| Karpathy guidelines | explicit assumption, simplicity, scope, and verification rules |
| brainstorming, writing-plans, grill-with-docs | lifecycle skill routing |
| subagent-driven implementation | package-level bounded implementation and review |
| systematic debugging | containment plus root-cause correction lifecycle |
| goal consistency | immutable IDs, pinned baseline, approval binding, change invalidation |
| early TEST/PROD isolation | Environment Contract in system design |
| minimized token use | CodeGraph-first retrieval, deterministic tools, package context, measured budgets |
| no fake frontend without backend/data | cross-layer contracts plus runtime probes |
| real deployment considered early | Release Manifest, fidelity gaps, TEST release, rollback |
| fewer meaningful gates | three executable CI gate classes and five hard stops |

## 24. Deferred Decisions

The following are deliberately deferred until evidence justifies them:

- multi-repository federation;
- multi-parent contract inheritance;
- general-purpose semantic contract inference;
- graph-database storage;
- uniform independent review for low-risk packages;
- full legacy backfill before touched-surface migration.

Deferral is a scope decision, not an unfilled design placeholder.
