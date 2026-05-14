# Workflow

Follow this sequence exactly. Do not skip, merge, or reorder gates.

## 0. Environment Check

Commands:

```bash
gh auth status
gh project --help
openspec --version
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
- Worktree state is understood and unrelated user changes are not touched.

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
- Ambiguities are resolved or recorded as blocking questions.

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
```

Skills:

- `idea-refine`
- `spec-driven-development`
- `superpowers:brainstorming`

Gate:

- `proposal.md` exists at the path printed by OpenSpec.
- Proposal links Project item and issue.
- Proposal review is recorded and approved before specs begin.

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
- `superpowers:brainstorming`

Gate:

- Every capability has `openspec/changes/<change-name>/specs/<capability>/spec.md`.
- Every capability has `openspec/changes/<change-name>/reviews/specs/<capability>.review.md`.
- Every spec review has `Decision: Approved`.
- Design work is forbidden until all spec reviews are approved.

## 7. Design Gate

Commands:

```bash
openspec instructions design --change <change-name>
```

Skills:

- `source-driven-development`
- `doubt-driven-development` for high-risk or unfamiliar decisions
- `documentation-and-adrs` for architectural decisions
- `superpowers:brainstorming`

Gate:

- `design.md` exists at the path printed by OpenSpec.
- Design explains architecture, data flow, boundaries, error handling, migration, rollout, observability, and test strategy when relevant.
- Design review is approved before tasks begin.

## 8. Tasks Gate

Commands:

```bash
openspec instructions tasks --change <change-name>
openspec status --change <change-name>
openspec validate <change-name> --type change --strict --no-interactive
```

Skills:

- `planning-and-task-breakdown`
- `superpowers:writing-plans`

Gate:

- `tasks.md` exists at the path printed by OpenSpec.
- Tasks are ordered, test-first, and traceable to specs/design.
- Tasks review is approved.
- OpenSpec strict validation passes before implementation.

## 9. Implementation Gate

Commands:

```bash
git status --short
```

Skills:

- `incremental-implementation`
- `superpowers:test-driven-development`
- Domain-specific agent-skills from `skill-map.md`

Gate:

- Each task starts with a failing test when behavior changes.
- RED failure is verified before implementation.
- GREEN pass is verified after implementation.
- `tasks.md` checkboxes are updated only with evidence.
- Commit after each coherent slice.

## 10. Local Verification Gate

Commands:

```bash
openspec validate <change-name> --type change --strict --no-interactive
git diff --check
```

Skills:

- `debugging-and-error-recovery`
- `browser-testing-with-devtools` for browser features
- `performance-optimization` for performance-sensitive work

Gate:

- OpenSpec validation passes.
- Project-specific tests, build, lint, and manual checks pass.
- Failures are fixed or explicitly documented as blockers.

## 11. Code Review Gate

Commands:

```bash
gh pr view <pr-number> --json number,title,body,state,url
gh pr checks <pr-number>
```

Skills:

- `code-review-and-quality`
- `security-and-hardening` for security-sensitive changes
- `doubt-driven-development` for high-risk changes

Gate:

- Review findings are listed by severity.
- Required findings are fixed.
- CI checks pass.
- OpenSpec artifacts are updated if implementation changes behavior.

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
