# Codex Contract Delivery

This context defines the language used by the Codex-based large-project delivery workflow. It separates approved intent, actual implementation, and runtime evidence so that no artifact is treated as authoritative outside its own domain.

## Language

**Project Baseline**:
The approved project-level goals, domain rules, quality attributes, system boundaries, and environment constraints that every delivery must preserve.
_Avoid_: Master spec, complete project document

**Requirement Scenario**:
An immutable, versioned statement of an observable outcome that must be satisfied and verified.
_Avoid_: Requirement item, feature note, acceptance bullet

**Contract Spine**:
The traceable relationship from an approved Requirement Scenario through intended experience, interfaces, data ownership, implementation, verification, and release evidence.
_Avoid_: Spec tree, document stack

**Effective Contract**:
The Project Baseline plus one Delivery Contract, resolved without copying or weakening the baseline.
_Avoid_: Merged spec, inherited document

**Delivery Package**:
A bounded unit of change that can reach a safe, independently verifiable outcome. A package may deliver a feature, enabler, migration, remediation, or incident correction.
_Avoid_: Frontend task, backend task, micro-task

**Delivery Contract**:
The approved goals, scenarios, scope, risks, cross-layer impacts, environment obligations, and completion conditions for one Delivery Package.
_Avoid_: Task list, implementation log

**Design Baseline**:
The approved intended experience and technical design, including the pinned Penpot revision and relevant system decisions.
_Avoid_: Latest screenshot, local mockup

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
An approval attached to exact immutable revisions of the relevant baseline, design, contract, plan, or release. A changed revision invalidates the approval.
_Avoid_: Approved flag, checkbox

**Legacy Exemption**:
A time-bounded, owned record of pre-existing non-conformance that is allowed temporarily while new or touched surfaces follow the current workflow.
_Avoid_: Permanent exception, ignored debt

**Safe Checkpoint**:
A verified state from which work may stop without leaving a partial migration, unsafe deployment, broken shared contract, or unrecoverable data change.
_Avoid_: Convenient stopping point

**Change Level**:
The minimum approval impact derived from the kind of contract node changed: L0 for internal implementation, L1 for design detail that preserves observable behavior, and L2 for goal, behavior, authority, compatibility, data meaning, or production-risk change.
_Avoid_: Agent-selected severity
