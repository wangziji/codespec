# Codex Contract Delivery

This context defines the language used by the Codex-based large-project delivery workflow. It separates approved intent, actual implementation, and runtime evidence so that no artifact is treated as authoritative outside its own domain.

## Language

**Project Baseline**:
The approved project-level goals, domain rules, and quality attributes that every delivery must preserve, plus immutable references to the owned architecture and Environment Contracts.
_Avoid_: Master spec, complete project document

**Requirement Scenario**:
An immutable, versioned statement of an observable outcome that must be satisfied and verified.
_Avoid_: Requirement item, feature note, acceptance bullet

**Contract Spine**:
The traceable relationship from an approved Requirement Scenario through intended experience, interfaces, data ownership, implementation, verification, and release evidence.
_Avoid_: Spec tree, document stack

**Code Graph**:
The observed structural relationships among source symbols, modules, interfaces, and tests. It explains likely code impact but does not define approved product intent.
_Avoid_: Complete architecture truth, proof of absence

**Contract Graph**:
The resolved view of which goals, scenarios, intended designs, interfaces, data ownership, delivery work, verification, and release evidence must agree.
_Avoid_: Knowledge graph, second specification

**Execution Graph**:
The allowed workflow states and guarded transitions for a Delivery Package, including correction, recovery, approval, and stopping paths.
_Avoid_: Task checklist, unrestricted agent loop

**Effective Contract**:
The Project Baseline plus one Delivery Contract, resolved without copying or weakening the baseline.
_Avoid_: Merged spec, inherited document

**Delivery Package**:
A bounded unit of change that can reach a safe, independently verifiable outcome. A package may deliver a feature, enabler, migration, remediation, or incident correction.
_Avoid_: Frontend task, backend task, micro-task

**Delivery Contract**:
The sole package delta for one Delivery Package: immutable references to owned goals and scenarios plus explicit scope, risks, cross-layer changes, environment obligations, and completion conditions. It does not copy baseline or owner facts.
_Avoid_: Task list, implementation log

**Design Baseline**:
A generated, immutable approval-binding view that resolves the pinned Penpot revision and owned architecture and Environment Contract references. It is not edited independently.
_Avoid_: Latest screenshot, local mockup, second design document

**Actual State**:
The currently observed code, deployed configuration, data shape, and runtime behavior. Actual State may contradict approved intent and never silently replaces it.
_Avoid_: Source of truth

**Evidence Attestation**:
An immutable, provenance-bearing record that identifies what was verified, where, against which release and contract revisions, and with what result.
_Avoid_: Test note, copied console output

**Environment Contract**:
The approved isolation, identity, topology, fidelity, migration, observability, and safety constraints for CI, TEST, and PROD.
_Avoid_: Environment file, deployment notes

**Release Manifest**:
The immutable identity of a release candidate, covering application artifacts, migrations, configuration schema, deployment definitions, infrastructure versions, and evidence references.
_Avoid_: Image tag, version string

**Approval Binding**:
An approval attached to exact immutable revisions of the relevant baseline, design, contract, plan, Workflow Release, evidence, or product release. A changed revision invalidates the approval.
_Avoid_: Approved flag, checkbox

**Legacy Exemption**:
A time-bounded, owned record of pre-existing non-conformance that is allowed temporarily while new or touched surfaces follow the current workflow.
_Avoid_: Permanent exception, ignored debt

**Safe Checkpoint**:
A verified state from which work may stop without leaving a partial migration, unsafe deployment, broken shared contract, or unrecoverable data change.
_Avoid_: Convenient stopping point

**Execution Loop**:
The bounded cycle that observes Actual State, selects the smallest in-scope action, verifies the result, and either adjusts, stops safely, or escalates.
_Avoid_: Keep trying, autonomous conversation

**Learning Signal**:
An attributed observation from delivery or operation that remains quarantined until deterministic provenance, access, redaction, retention, and freshness checks admit it. It may justify a future workflow improvement but has no authority to change the active workflow.
_Avoid_: Automatic memory, agent opinion

**Evolution Candidate**:
A remediation Delivery Contract that solely represents a versioned proposal to change an untrusted declarative extension payload such as a prompt pack, route entry, retrieval selector, package heuristic, advisory validator rule, or non-authoritative memory. It cannot carry executable skills, scripts, hooks, tool manifests, permissions, credentials, evaluators, or gate validators.
_Avoid_: Self-update, live policy mutation

**Workflow Release**:
An approved, immutable version of the delivery workflow with exact parent and content digests that can be canaried, promoted, monitored, and rolled back independently of a product Release Manifest.
_Avoid_: Latest skill, current prompt

**Trusted Workflow Core**:
The immutable, machine-enforced part of one approved Workflow Release that controls state transitions, protected surfaces, all mutating capabilities, evaluation, approvals, evidence, promotion, and rollback and cannot be changed or bypassed by an Evolution Candidate.
_Avoid_: Agent policy, editable guardrail

**Core Maintenance Package**:
A rare Delivery Package that repairs the Trusted Workflow Core through a separately pinned bootstrap verifier, existing Gate 3 and Gate 4 approvals, independent review, migration and recovery evidence, and dual-version rollback. It is outside the Evolution Loop and adds no routine review type.
_Avoid_: Evolution Candidate, self-update, emergency unreviewed patch

**Change Level**:
The minimum approval impact derived from the kind of contract node changed: L0 for internal implementation, L1 for design detail that preserves observable behavior, and L2 for goal, behavior, authority, compatibility, data meaning, or production-risk change.
_Avoid_: Agent-selected severity
