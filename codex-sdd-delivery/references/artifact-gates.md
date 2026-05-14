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
- Proposal review is approved.

Stops when:

- Capabilities are missing.
- Scope is too broad for one branch.
- Proposal conflicts with issue or Project item.

## Specs Gate

Passes when:

- Each capability has `specs/<capability>/spec.md`.
- Each requirement uses normative language.
- Every requirement has at least one `#### Scenario:`.
- Each capability has `reviews/specs/<capability>.review.md`.
- Every spec review says `Decision: Approved`.

Stops when:

- Any spec review is missing.
- Any spec review requests changes.
- Any scenario is not testable.
- Any spec conflicts with existing canonical specs.

## Design Gate

Passes when:

- `design.md` exists at the OpenSpec output path.
- Design covers architecture, data flow, boundaries, error handling, test strategy, and rollout where relevant.
- Design review is approved.

Stops when:

- Design makes unreviewed behavior changes.
- Design skips security, migration, or compatibility concerns that apply.
- Design contradicts specs.

## Tasks Gate

Passes when:

- `tasks.md` exists at the OpenSpec output path.
- Tasks are ordered by dependency.
- Each behavior-changing task starts with a failing test.
- Tasks review is approved.
- OpenSpec strict validation passes.

Stops when:

- Tasks are vague.
- Tasks cannot be verified.
- Tasks do not trace back to specs.
- `openspec validate` fails.

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
- CI and required reviews pass.

Stops when:

- PR body lacks evidence.
- Required reviews or CI fail.
- Project status does not match reality.
