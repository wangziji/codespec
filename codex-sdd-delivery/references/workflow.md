# Workflow

Follow this sequence exactly. Do not skip, merge, or reorder gates.

## 0. Environment Check

Commands:

```bash
gh auth status
gh project --help
openspec --version
codegraph --version
codegraph status .
git status --short --branch
```

Skills:

- `github`
- `using-agent-skills`
- `context-engineering`

Gate:

- GitHub CLI is authenticated.
- Token has `project` scope when Project operations are needed.
- OpenSpec CLI is available.
- CodeGraph CLI is available.
- CodeGraph is initialized and `codegraph status .` reports the index is up to date. If not, run `codegraph init -i .` before continuing.
- Worktree state is understood and unrelated user changes are not touched.
- Assumptions, constraints, and verification expectations for the selected work are recorded before artifact authoring begins.

## 1. Select Work From GitHub Project

Commands:

```bash
gh project item-list <project-number> --owner <owner> --format json
gh project field-list <project-number> --owner <owner> --format json
```

Skills:

- `github`
- `idea-refine`
- `context-engineering`
- `superpowers:brainstorming`

Gate:

- Exactly one Project item is selected.
- Item priority, status, dependencies, and acceptance criteria are understood.
- If no issue exists, create or request one before OpenSpec work.
- If multiple valid interpretations remain, they are surfaced and resolved or recorded as blockers.

## 2. Align GitHub Issue

Commands:

```bash
gh issue view <issue-number> --json number,title,body,labels,state,url
gh issue edit <issue-number> --add-label sdd
```

Skills:

- `github`
- `spec-driven-development`
- `superpowers:brainstorming`

Gate:

- Issue describes problem, scope, acceptance criteria, and out-of-scope items.
- Issue links to the Project item.
- Existing code context has been discovered with CodeGraph when the issue affects code.
- Ambiguities are resolved or recorded as blocking questions.
- A simplest-viable implementation direction is identified before proposal writing starts.

## 3. Create Branch

Commands:

```bash
git fetch origin
git switch <default-branch>
git pull --ff-only
git switch -c feature/<issue-number>-<short-slug>
```

Use the repository default branch, such as `main` or `master`, for `<default-branch>`.

Skills:

- `git-workflow-and-versioning`

Gate:

- Branch name links to the issue and future OpenSpec change.
- No unrelated user changes are staged or overwritten.

## 4. Create OpenSpec Change

Commands:

```bash
openspec init --tools codex .
openspec update .
openspec new change <issue-number>-<short-slug> --description "<issue title>"
openspec status --change <issue-number>-<short-slug>
```

Skills:

- `spec-driven-development`

Gate:

- Change path exists at `openspec/changes/<issue-number>-<short-slug>/`.
- GitHub issue and Project item record the OpenSpec change path.

## 5. Proposal Gate

Commands:

```bash
openspec instructions proposal --change <change-name>
codegraph files --path . --format tree
codegraph query --path . "<existing capability or symbol>"
```

Skills:

- `idea-refine`
- `spec-driven-development`
- **REQUIRED HARD GATE:** `superpowers:brainstorming`
- Proposal Reviewer Agent from `reviewer-agents.md`

Gate:

- `proposal.md` exists at the path printed by OpenSpec.
- Proposal links Project item and issue.
- Proposal references CodeGraph-discovered existing code boundaries when code changes are expected.
- `superpowers:brainstorming` was used to refine the proposal before review.
- `proposal.md` is written in Chinese, except for literal identifiers or commands that must remain unchanged.
- Proposal states key assumptions, scope boundaries, and explicit out-of-scope items.
- Proposal prefers the smallest change set that can satisfy the issue.
- Independent proposal review is recorded and approved before specs begin.

## 6. Specs Gate

Commands:

```bash
openspec instructions specs --change <change-name>
```

Skills:

- `spec-driven-development`
- `api-and-interface-design` when API or module contracts are involved
- `frontend-ui-engineering` when UI behavior is involved
- `security-and-hardening` when auth, permissions, user input, secrets, or privacy are involved
- `performance-optimization` when latency, throughput, or resource usage matters
- **REQUIRED HARD GATE:** `superpowers:brainstorming`
- Spec Reviewer Agent per capability from `reviewer-agents.md`

Gate:

- Every capability has `openspec/changes/<change-name>/specs/<capability>/spec.md`.
- `superpowers:brainstorming` was used to refine every capability spec before review.
- Every `spec.md` is written in Chinese, except for literal identifiers or commands that must remain unchanged.
- Every `spec.md` records assumptions or invariants that materially affect behavior.
- Specs avoid speculative options, future-facing flexibility, or requirements not requested by the issue or proposal.
- Every capability has `openspec/changes/<change-name>/reviews/specs/<capability>.review.md`.
- Every spec review has `Decision: Approved`.
- Spec reviewer agents did not author or modify the reviewed specs.
- Design work is forbidden until all spec reviews are approved.

## 7. Design Gate

Commands:

```bash
openspec instructions design --change <change-name>
codegraph impact --path . <symbol>
codegraph callers --path . <symbol>
codegraph callees --path . <symbol>
```

Skills:

- `source-driven-development`
- `doubt-driven-development` for high-risk or unfamiliar decisions
- `documentation-and-adrs` for architectural decisions
- **REQUIRED HARD GATE:** `superpowers:brainstorming`
- Design Reviewer Agent from `reviewer-agents.md`

Gate:

- `design.md` exists at the path printed by OpenSpec.
- Design explains architecture, data flow, boundaries, error handling, migration, rollout, observability, and test strategy when relevant.
- Design uses CodeGraph evidence for existing code boundaries, caller/callee relationships, and impact radius when code changes are expected.
- `superpowers:brainstorming` was used to refine the design before review.
- `design.md` is written in Chinese, except for literal identifiers or commands that must remain unchanged.
- Design documents the chosen simplest viable approach and names rejected higher-complexity options when that tradeoff matters.
- Design keeps changes surgical by mapping affected modules and explicitly excluding unrelated refactors.
- Independent design review is approved before tasks begin.

## 8. Tasks Gate

Commands:

```bash
openspec instructions tasks --change <change-name>
openspec status --change <change-name>
openspec validate <change-name> --type change --strict --no-interactive
codegraph affected --path . <changed-files>
```

Skills:

- `planning-and-task-breakdown`
- **REQUIRED HARD GATE:** `superpowers:writing-plans`
- Tasks Reviewer Agent from `reviewer-agents.md`

Gate:

- `tasks.md` exists at the path printed by OpenSpec.
- Tasks are ordered, test-first, and traceable to specs/design.
- Tasks identify likely implementation files and affected tests using CodeGraph when code changes are expected.
- `superpowers:writing-plans` was used to produce or refine the implementation plan.
- `tasks.md` is written in Chinese, except for literal identifiers or commands that must remain unchanged.
- Each non-trivial task includes an explicit verification target, such as a failing test, passing test, validation command, review check, or observable artifact.
- Tasks avoid speculative cleanup or unrelated improvement work.
- Independent tasks review is approved.
- OpenSpec strict validation passes before implementation.

## 9. Implementation Gate

Commands:

```bash
git status --short
codegraph status .
codegraph query --path . "<symbol-or-search-text>"
```

Skills:

- `incremental-implementation`
- `superpowers:test-driven-development` inside implementation slices
- **REQUIRED HARD GATE:** `superpowers:subagent-driven-development`
- Domain-specific agent-skills from `skill-map.md`

Gate:

- Implementation plan execution uses `superpowers:subagent-driven-development` with fresh implementer and reviewer subagents.
- Each task starts with a failing test when behavior changes.
- Code lookup, symbol search, caller/callee discovery, impact analysis, and affected-test discovery use CodeGraph before raw grep/find/read sweeps.
- Implementers state assumptions that affect behavior before coding or before changing the plan.
- Implementation chooses the minimum code path that satisfies the approved artifacts.
- File edits remain surgical and directly trace to the active task.
- RED failure is verified before implementation.
- GREEN pass is verified after implementation.
- `tasks.md` checkboxes are updated only with evidence.
- Commit after each coherent slice.

## 10. Local Verification Gate

Commands:

```bash
openspec validate <change-name> --type change --strict --no-interactive
codegraph status .
git diff --check
```

Skills:

- `debugging-and-error-recovery`
- `browser-testing-with-devtools` for browser features
- `performance-optimization` for performance-sensitive work

Gate:

- OpenSpec validation passes.
- CodeGraph index is up to date.
- Project-specific tests, build, lint, and manual checks pass.
- Failures are fixed or explicitly documented as blockers.

## 11. Code Review Gate

Commands:

```bash
gh pr view <pr-number> --json number,title,body,state,url
gh pr checks <pr-number>
codegraph impact --path . <changed-symbol>
```

Skills:

- **REQUIRED HARD GATE:** `code-review-and-quality`
- `security-and-hardening` for security-sensitive changes
- `doubt-driven-development` for high-risk changes
- Code Reviewer Agent from `reviewer-agents.md`

Gate:

- `code-review-and-quality` was used before merge readiness is claimed.
- Review findings are listed by severity.
- Code review uses CodeGraph impact/caller/callee queries for code-changing work.
- Review findings and merge-readiness notes for this workflow are written in Chinese, except for literal identifiers or commands that must remain unchanged.
- Code review explicitly checks for unnecessary complexity, hidden assumptions, unrelated edits, and missing verification evidence.
- Required findings are fixed.
- CI checks pass.
- OpenSpec artifacts are updated if implementation changes behavior.
- Code reviewer agent did not author the implementation slice under review.

## 12. Pull Request Gate

Commands:

```bash
gh pr create --title "<title>" --body-file /tmp/<change-name>-pr.md
gh pr edit <pr-number> --body-file /tmp/<change-name>-pr.md
```

Skills:

- `github`
- `git-workflow-and-versioning`
- `documentation-and-adrs`

Gate:

- PR body includes Project, issue, OpenSpec path, spec reviews, design/tasks review, tests, risks, and remaining work.
- Project item status moves to Code Review or equivalent.

## 13. Merge and Archive Gate

Commands:

```bash
gh pr checks <pr-number>
gh pr merge <pr-number> --squash --delete-branch
openspec archive <change-name> --yes
```

Skills:

- `shipping-and-launch`
- `ci-cd-and-automation`
- `github`

Gate:

- PR is merged only after required review and CI pass.
- OpenSpec change is archived after merge.
- Project item moves to Done only after merge and archive evidence exists.
