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
- `proposal.md` is written in Chinese.
- Proposal states assumptions, scope boundaries, and out-of-scope items explicitly.
- Proposal prefers the smallest change set that can satisfy the issue.
- Independent proposal review is approved.

Stops when:

- Capabilities are missing.
- Proposal work skipped `superpowers:brainstorming`.
- `proposal.md` is written primarily in English instead of Chinese.
- Material assumptions are left implicit.
- Scope is too broad for one branch.
- Proposal adds speculative future work or flexibility not requested by the issue.
- Proposal conflicts with issue or Project item.
- The proposal reviewer agent authored or edited the proposal.

## Specs Gate

Passes when:

- Each capability has `specs/<capability>/spec.md`.
- Each requirement uses normative language.
- Every requirement has at least one `#### Scenario:`.
- `superpowers:brainstorming` was used for spec refinement.
- Every capability `spec.md` is written in Chinese.
- Specs record assumptions or invariants that materially affect behavior.
- Specs stay within approved scope and avoid speculative requirements.
- Each capability has `reviews/specs/<capability>.review.md`.
- Every spec review says `Decision: Approved`.
- Spec reviewer agents did not author or edit the reviewed specs.

Stops when:

- Any spec review is missing.
- Spec work skipped `superpowers:brainstorming`.
- Any capability `spec.md` is written primarily in English instead of Chinese.
- Any material assumption remains implicit.
- Any spec review requests changes.
- Any scenario is not testable.
- Any spec adds flexibility, configurability, or future-facing requirements that were not requested.
- Any spec conflicts with existing canonical specs.
- A spec reviewer agent approves its own spec.

## Design Gate

Passes when:

- `design.md` exists at the OpenSpec output path.
- Design covers architecture, data flow, boundaries, error handling, test strategy, and rollout where relevant.
- Design uses CodeGraph impact, caller, or callee evidence when code changes are expected.
- `superpowers:brainstorming` was used for design refinement.
- `design.md` is written in Chinese.
- Design documents the simplest viable approach for the approved scope.
- Design maps the intended blast radius and excludes unrelated refactors.
- Independent design review is approved.

Stops when:

- Design makes unreviewed behavior changes.
- Design work skipped `superpowers:brainstorming`.
- `design.md` is written primarily in English instead of Chinese.
- Design introduces unnecessary architecture or speculative extensibility.
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
- `tasks.md` is written in Chinese.
- Each non-trivial task defines explicit verification evidence.
- Tasks stay surgical and avoid unrelated cleanup or refactoring.
- Independent tasks review is approved.
- OpenSpec strict validation passes.

Stops when:

- Tasks are vague.
- Tasks work skipped `superpowers:writing-plans`.
- `tasks.md` is written primarily in English instead of Chinese.
- Any non-trivial task lacks a concrete verification target.
- Tasks cannot be verified.
- Tasks do not trace back to specs.
- Tasks include speculative cleanup, abstraction, or feature work outside approved scope.
- `openspec validate` fails.
- The tasks reviewer agent authored or edited the tasks.

## Implementation Gate

Passes when:

- Each implementation slice follows RED, GREEN, REFACTOR.
- Implementation uses `superpowers:subagent-driven-development`.
- Code lookup and code search use CodeGraph before raw grep/find/read sweeps.
- Tests and validation evidence are recorded.
- `tasks.md` checkboxes reflect completed evidence only.
- Implementers surface assumptions that affect behavior before coding.
- Edits remain limited to the approved scope and affected files.

Stops when:

- Code was written before a failing test for behavior changes.
- Implementation skipped `superpowers:subagent-driven-development`.
- Raw grep/find/read sweeps were used for code discovery before CodeGraph without a recorded exception.
- Implementation adds speculative complexity or unrelated refactors.
- Verification evidence does not match the claimed completed work.
- Tests fail.
- Implementation changes behavior not covered by specs.

## PR Gate

Passes when:

- PR links Project item, issue, branch, and OpenSpec change.
- PR includes proposal, spec review, design review, tasks review, test, and risk evidence.
- PR evidence includes CodeGraph status for code-changing work.
- Code review is performed by an agent that did not author the implementation slice under review.
- Code review uses `code-review-and-quality`.
- Review artifacts and PR evidence text for this workflow are written in Chinese.
- Review explicitly checks hidden assumptions, unnecessary complexity, surgical scope, and verification evidence quality.
- CI and required reviews pass.

Stops when:

- PR body lacks evidence.
- Code review skipped `code-review-and-quality`.
- Review artifacts or PR evidence text are written primarily in English instead of Chinese.
- Review did not assess assumptions, complexity, or scope discipline.
- Required reviews or CI fail.
- Project status does not match reality.
