# Codex Contract Delivery Design

**Status:** Updated design direction; written specification pending final user review

**Date:** 2026-08-09

**Updated:** 2026-08-10

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
7. Use three bounded graphs and three bounded loops to make execution recoverable and learning explicit without creating a graph database or an autonomous self-modifying platform.
8. Keep the V1 orchestration runtime replaceable. Evaluate GitHub Spec Kit in an isolated implementation spike; do not require LangGraph or Temporal until measured workflow complexity justifies them.

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
- let an agent rewrite approved goals, evaluators, release gates, permissions, protected tests, or production policy;
- require a general agent-graph or durable-workflow platform before the lightweight V1 proves it needs one.

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
| Current workflow run state | Trusted state store and append-only transition events |
| Work queue and discussion status | GitHub Project, Issues, and Pull Requests |

The persisted state revision is the sole authority for execution eligibility. GitHub status is a revision-tagged intake command and projection; a manual move or stale automation cannot directly perform a transition. Projection mismatch blocks new execution until deterministic reconciliation. When other authorities disagree, the workflow reports drift. Actual runtime behavior never silently rewrites approved intent, and approved intent never substitutes for proof of actual runtime behavior.

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

Each fact type has one editable owner: product goals and scenarios in the Project Baseline, visual intent in Penpot, architectural boundaries in architecture records, interface/data definitions in repository contracts, and package-specific changes in the Delivery Contract. A Delivery Contract contains immutable owner references and explicit delta operations; validators reject copied baseline goals, scenarios, design rules, or interface definitions. It cannot become a second specification.

Canonical project files are sharded by stable module or record ID as they grow. Aggregate views, trace matrices, workflow status, budgets, candidate evaluations, Workflow Release registry entries, and evidence summaries are generated or immutable. They are not separately edited. Mutable Execution Graph state is not stored as an editable specification.

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

### 8.3 Three Graphs

The workflow exposes three bounded graph views. They have separate authorities and must not be collapsed into one general knowledge graph:

| Graph | Answers | Authority and boundary |
|---|---|---|
| Code Graph | What symbols, modules, callers, callees, and tests are structurally related? | CodeGraph plus source verification; it does not infer approved product intent |
| Contract Graph | Which goals, scenarios, Penpot states, interfaces, data owners, packages, tests, and release evidence must agree? | deterministic index over canonical contracts and attestations; it does not replace those sources |
| Execution Graph | Which workflow state may run next, under which guard, approval, budget, and recovery rule? | versioned workflow policy plus persisted run state; it does not decide business meaning |

Delivery Package dependencies remain a DAG. The Execution Graph may contain bounded backward edges for correction, recovery, and re-approval. Every cycle has an exit condition and a Safe Checkpoint; an unbounded conversational loop is invalid.

### 8.4 Three Loops

1. **Execution Loop:** Observe actual state -> plan the smallest next action -> act -> verify with deterministic evidence -> diagnose failure -> adjust -> stop, recover, or escalate. It runs inside one Delivery Package and may not expand scope.
2. **Learning Loop:** After accepted deliveries and incidents, quarantine attributed Learning Signals from human corrections, review findings, escaped defects, tool failures, CodeGraph fallbacks, token overruns, Penpot/runtime drift, and TEST/PROD fidelity gaps. Deterministic admission checks provenance, access, redaction, retention, and freshness. Admitted signals may produce candidates; no per-signal human gate exists, and no signal changes the active workflow.
3. **Evolution Loop:** Turn an admitted Learning Signal cluster into an Evolution Candidate, evaluate it in isolation, approve its canary plan through Human Gate 3, canary it within its declared risk scope, then accept or reject the result through Human Gate 4. Promotion is a release operation with an immutable version and evidence.

The loops operate at different cadences. Execution is synchronous with delivery. Learning is asynchronous and cross-package. Evolution is explicitly initiated and never delays an otherwise accepted Delivery Package.

### 8.5 Controlled Evolution Boundary

An agent may automatically collect and quarantine Learning Signals, cluster admitted failures, draft an Evolution Candidate, run non-protected offline evaluations, and open a reviewable change. It may propose content-addressed payloads for declared extension slots: prompt packs, model-route entries, retrieval selectors, package heuristics, advisory validator rules, and non-authoritative memory. These payloads are untrusted, interpretable, declarative control data; serializing model instructions as data does not make them safe or non-executable in effect.

The immutable **Trusted Workflow Core** from the currently approved Workflow Release performs state transitions, protected-surface and transitive-blast-radius classification, extension parsing, constraint enforcement, capability authorization, evaluation delegation, approval verification, evidence writing, promotion, and rollback. Its protected manifest covers the controller, extension interfaces and schemas, parsers, classification rules, executable skills, scripts, hooks, tool manifests, command implementations, policies, permissions, credential and capability broker, gate-enforcing validators, evaluator and holdout clients, evidence writer, approval verifier, and their transitive dependencies. A candidate cannot modify, replace, configure around, or route around that boundary; an advisory validator cannot become gate-enforcing through a payload.

Workers receive no direct credentials or unrestricted mutating tool channel. All repository, infrastructure, external-service, and deployment writes pass through the Trusted Workflow Core's allowlisted capability broker, which binds the pinned Workflow Release, run state, approval, resource scope, preconditions, idempotency or reconciliation rule, and audit event. Sandboxed worktree writes are a scoped broker capability, not ambient shell authority. A prompt, route, selector, heuristic, advisory rule, or memory item that attempts an undeclared tool call, changes its own capability scope, or emits executable code for the controller is rejected and quarantined.

An agent may not approve or directly activate its own candidate. It may never self-modify or bypass:

- Project Goals, Requirement Scenarios, or human approval policy;
- production credentials, permissions, deployment authorization, or security policy;
- audit history, Evidence Attestations, protected tests, hidden holdouts, evaluators, or release gates;
- the policy that defines which surfaces are protected from self-modification.

The candidate-producing agent may receive public-regression diagnostics, but protected evaluation precommits query and attempt budgets across the entire candidate lineage and returns only bounded results. The final sealed holdout is one-shot. Failure rejects that lineage; a successor must be a materially new, versioned candidate and receives no additional protected diagnostics.

An Evolution Candidate declares expected surfaces and risk tiers, but the Trusted Workflow Core derives the transitive reachable blast radius. A canary may be scoped, but Workflow Release promotion is global and requires protected evaluation, risk-matched canary evidence, and unaffected-surface regressions across every derived reachable scope. If that coverage is infeasible, the candidate is split or rejected; a narrow canary never authorizes an incompletely evaluated global release.

An Evolution Candidate is represented solely by the Delivery Contract of a `remediation` Delivery Package. Human Gate 3 binds the exact candidate and canary-plan hashes. A trusted workflow-canary attestation binds `candidate_digest`, `canary_plan_hash`, `target_workflow_release_digest`, `monitoring_spec_hash`, derived-scope coverage, window start/end, and result evidence. Human Gate 4 and `promote` verify and bind that complete tuple; evidence from another candidate, plan, scope, or window cannot be replayed. The monitoring specification defines start and completion criteria, observation duration, abort thresholds, and rollback triggers. Any change invalidates the affected approval. Controlled evolution adds no fifth routine review type.

Trusted Workflow Core immutability is per Workflow Release, not a ban on maintaining the platform. A rare **Core Maintenance Package** repairs a core security, correctness, compatibility, or operability defect; it is not generated or activated by the Evolution Loop. It reuses Human Gates 3 and 4, plus production operation authorization only when applicable, and requires a separately pinned bootstrap verifier, independent review, exact old/new core digests, state and schema migration, compatibility and recovery tests, dual-version rollback, and a Safe Checkpoint. The workflow being replaced cannot be its sole author, implementer, verifier, or approver. Ordinary Evolution Candidates remain absolutely unable to touch the core, and no fifth review type is introduced.

Promotion requires a versioned candidate diff, provenance, fixed historical regression set, sealed holdout result, quality and safety thresholds, cost comparison, independent review, Gate 3 approval, scoped canary, monitoring window, Gate 4 acceptance, and executable rollback. A cost reduction cannot compensate for a quality, safety, scope, or production regression.

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
- Release Manifest digest, for production authorization;
- pinned Workflow Release digest, for every plan, run, approval, and Evidence Attestation;
- Evolution Candidate and canary-plan hashes, for workflow Gate 3;
- the complete trusted workflow-canary attestation tuple—Evolution Candidate, canary plan, target Workflow Release, monitoring-window specification, derived-scope coverage, window start/end, and result-evidence digests—for workflow Gate 4.

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
| `core-maintenance` | rare Trusted Workflow Core defect repair through the independent bootstrap path | no |
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

**Human Gate 4:** accept the verified result after the applicable product online regression or Workflow Release canary monitoring window. Production and high-risk infrastructure changes additionally require explicit operation authorization.

### Phase 10: Incident and Defect Handling

Contain damage first through a reversible rollback, traffic stop, or safe feature disable when necessary. Then use `superpowers:systematic-debugging` to reproduce, trace data flow, compare working patterns, test one hypothesis, write a failing test, correct the root cause, and re-run relevant release evidence. Three failed correction attempts trigger automated architectural diagnosis. Dependency-based invalidation reuses exactly the affected Human Gates 1-4; otherwise the package stops at a Safe Checkpoint with diagnosis evidence. It does not create a new review type or an unbounded fourth correction loop.

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
- pinned Workflow Release digest;
- immutable TEST evidence pointers.

Evidence Attestations are created by trusted CI/deployment identities and include environment identity, artifact digest, pinned Workflow Release digest, probe version, timestamp, result, and sanitized logs. Workflow-canary attestations additionally include the candidate, approved canary plan, target Workflow Release, monitoring specification, derived-scope coverage, and exact monitoring window. Evidence is append-only and retained outside mutable workspace files; the Delivery Package stores stable references.

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
│   ├── evidence
│   ├── learn
│   ├── evaluate
│   ├── promote
│   └── rollback
├── references/
├── schemas/
└── assets/
```

`SKILL.md` remains a short trigger and router. References load by current phase. Repository policy pins compatible schema and validator versions; CI vendors or locks its runtime. Local tooling refuses unknown major schema versions. `doctor` verifies CodeGraph, Penpot capability, GitHub, CI/deployment prerequisites, validator compatibility, and environment access before work begins.

`learn` operates only on deterministically admitted Learning Signals and creates a remediation Delivery Contract as the sole Evolution Candidate proposal. `evaluate`, `promote`, and candidate-scoped `rollback` require that candidate. The approved Trusted Workflow Core executes them. `evaluate` delegates protected cases to a trusted evaluator; `promote` requires Gate 3, complete derived-scope evidence, and Gate 4 acceptance. Each candidate records exact parent and result Workflow Release digests. Rollback atomically revokes new dispatch and resumption for the failed digest, reconciles started effects, drives affected runs to a Safe Checkpoint, quarantines candidate-only outputs, and restores the recorded predecessor with compare-and-swap. Resumption then requires an approval-bound migration; it never silently switches semantics. Ambiguous descendant histories reject rollback. None of these commands may mutate an active Delivery Contract.

Core maintenance runs through a separately pinned, minimal bootstrap verifier rather than candidate `promote`. The verifier accepts only a `core-maintenance` Delivery Contract with independent review and bound Gate 3/4 records, verifies the protected manifest and old/new digests, exercises state/schema migration and both rollback directions, and performs the same fenced journal transition. It cannot evaluate general Evolution Candidate payloads or expand worker permissions.

## 20. Framework Adoption and Runtime Boundary

The design adopts capabilities, not a framework-owned truth model.

### 20.1 V1 Runtime

V1 uses the Codex Skill, repository contracts, a small persisted state machine, GitHub approvals, and deterministic CI/deployment jobs. Every Delivery Contract and run pins an exact Workflow Release digest; global promotions affect new runs only. Resumption uses the pinned release unless it is revoked or an explicit migration reuses the package-plan approval gate.

The state store owns one transactional journal. A transition atomically appends its state change and side-effect intent. Before dispatch, a worker acquires a persisted attempt identity through compare-and-swap with lease and fencing semantics. A takeover must fence the stale worker and reconcile the prior attempt before another effect may be issued. Effects progress through `intent`, `started`, `prepared`, `completed`, and typed reconciliation states. `prepared` is durable write-ahead authority for a content-addressed result and is required before host mutation. External operations use an idempotency key when supported; otherwise the transition defines preconditions, read-after-write reconciliation, compensation or rollback, and a manual escape path. Crash and concurrent-takeover behavior is tested before dispatch, after the external effect, and before completion recording. The persisted state contains identifiers, revisions, transitions, checkpoints, budgets, and evidence references rather than full agent transcripts. The agent is replaceable; the contracts and evidence remain usable without it.

Worker admission and runtime timing are separate authorities. An immutable grant determines whether dispatch may begin. At the actual `STARTED` transition, the journal atomically verifies the current owner/fence, records `STARTED`, and re-anchors the same persisted attempt lease for the full policy worker timeout plus bounded termination and commit budgets. The subprocess still receives exactly the policy timeout. After `STARTED`, temporal authority comes from the fenced journal lease; grant expiry alone cannot invalidate an otherwise live attempt, while policy, Workflow Release, approval, run, resource, owner, or fence drift still denies commit. The exact Task 5 contract, recovery rules, and acceptance evidence are defined in [Task 5 Dispatch Authority Design](2026-08-15-task5-dispatch-authority-design.md).

### 20.2 Spec Kit Decision Spike

Before any Spec Kit adoption, an isolated, time-boxed decision spike checks a pinned version's documented capability and extension boundaries. If no supported integration boundary exists, the spike terminates before adapter implementation. Only discovered supported capabilities may proceed to comparison with the standalone Skill.

Spec Kit is adopted only if the spike proves all of the following:

- it does not create a second editable specification, plan, task, approval, or status truth;
- it can run without weakening Penpot, contract, environment, Release Manifest, or human gates;
- any supported interruption and resumption preserve exact revisions and do not repeat successful side effects;
- a clean project can pin and reproduce the selected version;
- a predeclared spike specification pins the standalone baseline, representative fixtures, versions, run count, measurements, and pass/fail thresholds;
- measured artifact volume, agent context, token use, and maintenance meet those thresholds.

Failure rejects the dependency without blocking the standalone design. The spike is disposable and cannot become production code by inertia.

### 20.3 Deferred Runtimes

LangGraph becomes a candidate only when repeated evidence shows that dynamic branching, cross-session checkpointing, or human interrupt/resume cannot be maintained safely by the small state machine. Temporal becomes a candidate only when cross-day, multi-system, side-effecting workflows require durable event history, compensation, and operational recovery beyond CI capabilities.

OpenHands, Microsoft Agent Framework, CrewAI, and AutoGen are not additional primary orchestration cores in V1. A future adapter may use one as a replaceable worker or runtime, but it cannot own requirements, approvals, release identity, or evidence.

## 21. Hard Stops

Only these conditions stop autonomous progression:

1. a material business or L2 change requires human decision;
2. the Effective Contract contains an unresolved conflict;
3. any check required by the Effective Contract, Package Verify, or Release Verify fails, regardless of incident severity;
4. a P0/P1 migration, environment, runtime, or release-safety failure exists;
5. production or high-risk infrastructure authorization is absent;
6. a token/review/correction stop-loss is reached after returning to a Safe Checkpoint;
7. trusted run state, transactional history, pinned Workflow Release, approval/evidence provenance, or evaluator isolation cannot be established;
8. an Evolution Candidate attempts to modify the Trusted Workflow Core, access a protected holdout, exceed its query budget, widen beyond evaluated scope, or promote without bound evidence and trusted approval.

Other findings are corrected automatically when within scope or recorded as non-blocking evidence.

## 22. Known Disadvantages and Trade-offs

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
- a workflow that is applied uniformly to trivial work becomes bureaucracy;
- three graph views add terminology and index-version responsibilities even though no graph database is built;
- persisted execution requires transition migrations, idempotency keys, and recovery tests;
- learning data can be poisoned, stale, privacy-sensitive, or biased toward recent failures;
- evaluation and hidden holdout maintenance cost engineering time and can still reward the wrong proxy;
- controlled evolution improves safety by making change slower and dependent on human review;
- capability brokering reduces prompt-driven privilege escalation but adds a high-value enforcement component and can limit useful tools until explicitly integrated;
- the independent Core Maintenance path prevents permanent core lock-in but adds a small bootstrap verifier whose own integrity and upgrades require exceptional care;
- a Spec Kit adapter may create upgrade and ecosystem coupling without enough benefit;
- later adding LangGraph or Temporal could create competing state machines unless one runtime clearly owns orchestration.

Mitigations are risk-based enforcement, brownfield ratcheting, standard contracts, hash-bound approvals, runtime evidence, package-level context, measured cost, and an explicit refusal to build the deferred full platform.

## 23. Required Behavior Tests for the Workflow

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
- a compliant end-to-end package reaches acceptance with immutable evidence;
- copied baseline or owner facts in a Delivery Contract fail validation;
- a stale or manually changed GitHub projection cannot execute a transition;
- a required P2 check blocks even when incident urgency is low;
- resuming from an Execution Graph checkpoint does not repeat a completed side effect;
- crashes at every side-effect boundary reconcile without silent duplication or lost completion;
- an Execution Loop with no remaining progress path stops at its configured bound;
- quarantined, stale, unauthorized, or poisoned Learning Signals cannot enter candidates, active skills, or memory;
- a candidate-producing agent cannot modify or route around the Trusted Workflow Core, hidden holdouts, evaluators, protected tests, permissions, audit evidence, or release gates;
- a candidate prompt or extension payload cannot directly invoke a mutating tool, obtain credentials, widen its broker capability, or inject controller code;
- protected holdout query limits and sealed-final-holdout isolation are enforced;
- lower token cost cannot promote a candidate that regresses quality, safety, or scope;
- a candidate cannot promote until every Trusted Workflow Core-derived reachable scope has risk-matched evidence;
- an in-flight run continues with its pinned Workflow Release after a new promotion;
- concurrent recovery workers cannot both dispatch the same fenced side-effect attempt;
- canary regression prevents promotion and quarantines outputs from the candidate release;
- a workflow-canary attestation from a different candidate, plan, derived scope, or monitoring window cannot satisfy Gate 4 or `promote`;
- rollback revokes the failed digest and prevents affected runs from dispatching or resuming before approval-bound migration;
- a Core Maintenance Package cannot pass without an independently pinned verifier, bound old/new digests, migration/recovery evidence, and dual-version rollback;
- candidate rollback targets its recorded predecessor and rejects ambiguous descendants;
- a parameterized approval test invalidates every bound baseline, design, Penpot, plan, Release Manifest, Workflow Release, candidate, and canary-evidence digest;
- rejecting the Spec Kit spike leaves the standalone Skill path complete and reproducible.

## 24. Requirement Coverage

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
| fewer meaningful gates | three executable CI gate classes and eight hard stops |
| loop and graph engineering | three bounded graph views, three cadence-separated loops, persisted checkpoints |
| controlled agent evolution | candidate evaluation, protected holdout, independent approval, canary, rollback |
| mature framework reuse without lock-in | evidence-gated Spec Kit spike and explicit runtime adoption thresholds |

## 25. Deferred Decisions

The following are deliberately deferred until evidence justifies them:

- multi-repository federation;
- multi-parent contract inheritance;
- general-purpose semantic contract inference;
- graph-database storage;
- uniform independent review for low-risk packages;
- full legacy backfill before touched-surface migration;
- production adoption of LangGraph or Temporal;
- automatic activation of any workflow, skill, policy, evaluator, or permission change.

Deferral is a scope decision, not an unfilled design placeholder.
