# Artifact Gates

Every gate has a pass condition and a stop condition. If a gate fails, stop, fix, and re-run the gate.

## GitHub Intake Gate

Passes when:

- Project item is selected.
- Issue exists and links to the Project item.
- Acceptance criteria and scope are clear.
- Branch name and OpenSpec change name are chosen.

Stops when:

- No issue or Project item can be linked.
- Acceptance criteria are ambiguous.
- Dependencies are unresolved.

## Proposal Gate

Passes when:

- `proposal.md` exists at the OpenSpec output path.
- Proposal links issue and Project item.
- Proposal states why, what changes, capabilities, impact, scope, and out-of-scope.
- Independent proposal review is approved.

Stops when:

- Capabilities are missing.
- Scope is too broad for one branch.
- Proposal conflicts with issue or Project item.
- The proposal reviewer agent authored or edited the proposal.

## Specs Gate

Passes when:

- Each capability has `specs/<capability>/spec.md`.
- Each requirement uses normative language.
- Every requirement has at least one `#### Scenario:`.
- Each capability has `reviews/specs/<capability>.review.md`.
- Every spec review says `Decision: Approved`.
- Spec reviewer agents did not author or edit the reviewed specs.

Stops when:

- Any spec review is missing.
- Any spec review requests changes.
- Any scenario is not testable.
- Any spec conflicts with existing canonical specs.
- A spec reviewer agent approves its own spec.

## Design Gate

Passes when:

- `design.md` exists at the OpenSpec output path.
- Design covers architecture, data flow, boundaries, error handling, test strategy, and rollout where relevant.
- Independent design review is approved.

Stops when:

- Design makes unreviewed behavior changes.
- Design skips security, migration, or compatibility concerns that apply.
- Design contradicts specs.
- The design reviewer agent authored or edited the design.

## Tasks Gate

Passes when:

- `tasks.md` exists at the OpenSpec output path.
- Tasks are ordered by dependency.
- Each behavior-changing task starts with a failing test.
- Independent tasks review is approved.
- OpenSpec strict validation passes.

Stops when:

- Tasks are vague.
- Tasks cannot be verified.
- Tasks do not trace back to specs.
- `openspec validate` fails.
- The tasks reviewer agent authored or edited the tasks.

## Implementation Gate

Passes when:

- Each implementation slice follows RED, GREEN, REFACTOR.
- Tests and validation evidence are recorded.
- `tasks.md` checkboxes reflect completed evidence only.

Stops when:

- Code was written before a failing test for behavior changes.
- Tests fail.
- Implementation changes behavior not covered by specs.

## PR Gate

Passes when:

- PR links Project item, issue, branch, and OpenSpec change.
- PR includes proposal, spec review, design review, tasks review, test, and risk evidence.
- Code review is performed by an agent that did not author the implementation slice under review.
- CI and required reviews pass.

Stops when:

- PR body lacks evidence.
- Required reviews or CI fail.
- Project status does not match reality.
