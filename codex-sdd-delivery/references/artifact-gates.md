# Artifact Gates

Every gate has a pass condition and a stop condition. If a gate fails, stop, fix, and re-run the gate.

## GitHub Intake Gate

Passes when:

- Project item is selected.
- Issue exists and links to the Project item.
- Acceptance criteria and scope are clear.
- CodeGraph is initialized and up to date before code-affecting work starts.
- Branch name and OpenSpec change name are chosen.

Stops when:

- No issue or Project item can be linked.
- CodeGraph is unavailable, uninitialized, or stale and cannot be repaired.
- Acceptance criteria are ambiguous.
- Dependencies are unresolved.

## Proposal Gate

Passes when:

- `proposal.md` exists at the OpenSpec output path.
- Proposal links issue and Project item.
- Proposal states why, what changes, capabilities, impact, scope, and out-of-scope.
- Proposal uses CodeGraph evidence for existing code boundaries when code changes are expected.
- `superpowers:brainstorming` was used for proposal refinement.
- Independent proposal review is approved.

Stops when:

- Capabilities are missing.
- Proposal work skipped `superpowers:brainstorming`.
- Scope is too broad for one branch.
- Proposal conflicts with issue or Project item.
- The proposal reviewer agent authored or edited the proposal.

## Specs Gate

Passes when:

- Each capability has `specs/<capability>/spec.md`.
- Each requirement uses normative language.
- Every requirement has at least one `#### Scenario:`.
- `superpowers:brainstorming` was used for spec refinement.
- Each capability has `reviews/specs/<capability>.review.md`.
- Every spec review says `Decision: Approved`.
- Spec reviewer agents did not author or edit the reviewed specs.

Stops when:

- Any spec review is missing.
- Spec work skipped `superpowers:brainstorming`.
- Any spec review requests changes.
- Any scenario is not testable.
- Any spec conflicts with existing canonical specs.
- A spec reviewer agent approves its own spec.

## Design Gate

Passes when:

- `design.md` exists at the OpenSpec output path.
- Design covers architecture, data flow, boundaries, error handling, test strategy, and rollout where relevant.
- Design uses CodeGraph impact, caller, or callee evidence when code changes are expected.
- `superpowers:brainstorming` was used for design refinement.
- Independent design review is approved.

Stops when:

- Design makes unreviewed behavior changes.
- Design work skipped `superpowers:brainstorming`.
- Design skips security, migration, or compatibility concerns that apply.
- Design contradicts specs.
- The design reviewer agent authored or edited the design.

## Tasks Gate

Passes when:

- `tasks.md` exists at the OpenSpec output path.
- Tasks are ordered by dependency.
- Tasks identify likely implementation files and affected tests using CodeGraph when code changes are expected.
- Each behavior-changing task starts with a failing test.
- `superpowers:writing-plans` was used for task planning.
- Independent tasks review is approved.
- OpenSpec strict validation passes.

Stops when:

- Tasks are vague.
- Tasks work skipped `superpowers:writing-plans`.
- Tasks cannot be verified.
- Tasks do not trace back to specs.
- `openspec validate` fails.
- The tasks reviewer agent authored or edited the tasks.

## Implementation Gate

Passes when:

- Each implementation slice follows RED, GREEN, REFACTOR.
- Implementation uses `superpowers:subagent-driven-development`.
- Code lookup and code search use CodeGraph before raw grep/find/read sweeps.
- Tests and validation evidence are recorded.
- `tasks.md` checkboxes reflect completed evidence only.

Stops when:

- Code was written before a failing test for behavior changes.
- Implementation skipped `superpowers:subagent-driven-development`.
- Raw grep/find/read sweeps were used for code discovery before CodeGraph without a recorded exception.
- Tests fail.
- Implementation changes behavior not covered by specs.

## PR Gate

Passes when:

- PR links Project item, issue, branch, and OpenSpec change.
- PR includes proposal, spec review, design review, tasks review, test, and risk evidence.
- PR evidence includes CodeGraph status for code-changing work.
- Code review is performed by an agent that did not author the implementation slice under review.
- Code review uses `code-review-and-quality`.
- CI and required reviews pass.

Stops when:

- PR body lacks evidence.
- Code review skipped `code-review-and-quality`.
- Required reviews or CI fail.
- Project status does not match reality.
