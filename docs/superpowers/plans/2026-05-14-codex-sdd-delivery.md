# Codex SDD Delivery Workflow Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new `codex-sdd-delivery` skill that orchestrates GitHub Project-first intake, GitHub issue/branch/PR delivery, OpenSpec CLI artifacts, agent-skills phase guidance, Superpowers hard gates, per-spec independent reviews, and final archive.

**Architecture:** Create a short entrypoint `SKILL.md` that defines the hard gate contract, then move detailed procedures into focused `references/*.md` files. Keep the new skill independent from the existing `codex-openspec-superpowers-github` skill so users can adopt it without breaking the current workflow.

**Tech Stack:** Codex skills markdown format, OpenSpec CLI 1.3.1, GitHub CLI 2.92+, GitHub Projects v2, agent-skills, Superpowers skills, `quick_validate.py`, shell validation commands.

---

## File Structure

- Create: `codex-sdd-delivery/SKILL.md`
  - Short triggerable skill entrypoint.
  - Declares the non-negotiable no-implementation-before-gates rule.
  - Points to all detailed references.
- Create: `codex-sdd-delivery/agents/openai.yaml`
  - UI metadata for the skill.
- Create: `codex-sdd-delivery/references/workflow.md`
  - End-to-end GitHub Project-first workflow with inputs, commands, skills, artifacts, and stop conditions.
- Create: `codex-sdd-delivery/references/github-project.md`
  - Project discovery, item selection, status transitions, field update rules, and drift prevention.
- Create: `codex-sdd-delivery/references/github-branch-pr.md`
  - Issue linkage, branch naming, commit rules, PR body rules, CI/review loop, and merge/cleanup.
- Create: `codex-sdd-delivery/references/openspec-cli.md`
  - Required OpenSpec CLI command sequence and artifact handling rules.
- Create: `codex-sdd-delivery/references/skill-map.md`
  - Stage-to-skill mapping across agent-skills and Superpowers.
- Create: `codex-sdd-delivery/references/artifact-gates.md`
  - Proposal, spec, design, tasks, validation, implementation, review, and PR gate definitions.
- Create: `codex-sdd-delivery/references/spec-review-template.md`
  - Independent per-capability spec review template and approval rules.
- Create: `codex-sdd-delivery/references/pr-template.md`
  - PR body template with Project, issue, OpenSpec, review, validation, and test evidence.
- Create: `codex-sdd-delivery/references/project-status-map.md`
  - Recommended Project statuses and allowed transitions.
- Modify: `README.md`
  - Document `codex-sdd-delivery` as the recommended Project-first workflow skill while keeping the older skill documented.
- Later automation candidate: `codex-sdd-delivery/scripts/check_sdd_delivery.py`
  - Defer until the document-only skill has been used on real work and repeated validation misses are known. Do not create in the first implementation pass.

## Dependency Graph

```text
Task 1: Skill shell
  -> Task 2: Workflow reference
    -> Task 3: GitHub Project reference
    -> Task 4: Branch/PR reference
    -> Task 5: OpenSpec CLI reference
    -> Task 6: Skill map
      -> Task 7: Artifact gates
        -> Task 8: Spec review template
        -> Task 9: PR template and status map
          -> Task 10: README update
            -> Task 11: Validation and installed-copy sync
```

## Task 1: Create the Skill Shell

**Files:**
- Create: `codex-sdd-delivery/SKILL.md`
- Create: `codex-sdd-delivery/agents/openai.yaml`

- [ ] **Step 1: Create the directory structure**

Run:

```bash
mkdir -p codex-sdd-delivery/agents codex-sdd-delivery/references
```

Expected: directories exist and no existing files are overwritten.

- [ ] **Step 2: Write `SKILL.md`**

Create `codex-sdd-delivery/SKILL.md` with exactly this content:

```markdown
---
name: codex-sdd-delivery
description: Use when Codex should run a full GitHub Project-first spec-driven delivery workflow with OpenSpec CLI, GitHub issues, branches, PRs, agent-skills, Superpowers gates, per-spec reviews, validation, and archive
---

# Codex SDD Delivery

## Core Rule

Do not write implementation code until GitHub intake is linked, OpenSpec proposal is reviewed, every capability spec has an independent approved review, design is reviewed, tasks are reviewed, OpenSpec strict validation passes, and the working branch is linked to the tracked GitHub issue or Project item.

## Required Reading

Before starting work, read these files in order:

1. `references/workflow.md`
2. `references/github-project.md`
3. `references/github-branch-pr.md`
4. `references/openspec-cli.md`
5. `references/skill-map.md`
6. `references/artifact-gates.md`
7. `references/spec-review-template.md`
8. `references/pr-template.md`
9. `references/project-status-map.md`

## Operating Model

- GitHub Project is the work queue and status source.
- GitHub Issue records discussion, scope, and acceptance criteria.
- Git branch isolates implementation.
- OpenSpec is the artifact contract.
- Per-spec reviews are mandatory gates, one review per capability spec.
- agent-skills provide phase-specific engineering methods.
- Superpowers enforce hard gates for brainstorming, planning, TDD, and verification.
- GitHub PR is the delivery evidence packet.

## Stop Conditions

Stop and repair before continuing when:

- GitHub Project item, issue, branch, OpenSpec change, or PR links are missing.
- Any proposal, spec, design, tasks, validation, implementation, review, or PR gate fails.
- Any spec review is missing or not approved.
- OpenSpec validation fails.
- Tests, build, lint, CI, or code review fail.
- Project status says a later phase than the artifacts support.

## Completion Rule

Work is complete only when the PR contains Project, issue, OpenSpec, test, review, and risk evidence; CI/reviews are resolved; the Project item status is current; and the OpenSpec change is archived after merge.
```

- [ ] **Step 3: Write `agents/openai.yaml`**

Create `codex-sdd-delivery/agents/openai.yaml` with exactly this content:

```yaml
interface:
  display_name: "Codex SDD Delivery"
  short_description: "Project-first SDD workflow for Codex"
  default_prompt: "Use $codex-sdd-delivery to deliver the next GitHub Project item through issue intake, OpenSpec artifacts, per-spec review, TDD implementation, code review, PR, and archive."
```

- [ ] **Step 4: Validate the shell**

Run:

```bash
python3 /Users/mark/.skills/.system/skill-creator/scripts/quick_validate.py /Users/mark/work/codex/codespec/codex-sdd-delivery
```

Expected: `Skill is valid!`

- [ ] **Step 5: Commit the shell**

Run:

```bash
git add codex-sdd-delivery/SKILL.md codex-sdd-delivery/agents/openai.yaml
git commit -m "feat: add codex sdd delivery skill shell"
```

Expected: one commit containing only the shell files. If the user has uncommitted unrelated changes, do not stage them.

## Task 2: Write the End-to-End Workflow Reference

**Files:**
- Create: `codex-sdd-delivery/references/workflow.md`

- [ ] **Step 1: Create `workflow.md`**

Create `codex-sdd-delivery/references/workflow.md` with exactly this content:

```markdown
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
git switch main
git pull --ff-only
git switch -c feature/<issue-number>-<short-slug>
```

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
```

- [ ] **Step 2: Check for missing gates**

Run:

```bash
rg -n "Gate:|Decision: Approved|openspec validate|gh project|gh pr" codex-sdd-delivery/references/workflow.md
```

Expected: output shows gate definitions for every major phase and commands for Project, PR, and OpenSpec validation.

- [ ] **Step 3: Commit workflow reference**

Run:

```bash
git add codex-sdd-delivery/references/workflow.md
git commit -m "docs: add sdd delivery workflow reference"
```

Expected: one commit containing only `workflow.md`.

## Task 3: Write GitHub Project Rules

**Files:**
- Create: `codex-sdd-delivery/references/github-project.md`
- Create: `codex-sdd-delivery/references/project-status-map.md`

- [ ] **Step 1: Create `github-project.md`**

Create `codex-sdd-delivery/references/github-project.md` with exactly this content:

```markdown
# GitHub Project First

GitHub Project is the source of truth for what Codex should work on next.

## Required Discovery

Run these commands before selecting work:

```bash
gh auth status
gh project item-list <project-number> --owner <owner> --format json
gh project field-list <project-number> --owner <owner> --format json
```

If `gh auth status` does not show `project` scope, run:

```bash
gh auth refresh -s project
```

## Item Selection Rules

Select work in this order:

1. Highest priority unblocked item.
2. Item whose dependencies are already Done or not required.
3. Item with a linked issue or enough body detail to create one.
4. Item whose scope fits one short-lived branch and PR.

Do not pick a random issue when a Project item is available.

## Required Item Links

Each active Project item must track:

- GitHub issue URL.
- Branch name.
- OpenSpec change path.
- PR URL after PR creation.
- Current gate.
- Latest validation evidence.
- Latest review evidence.

## Project Updates

Update the Project item at these transitions:

- selected -> `Specifying`
- proposal review approved -> `Spec Review`
- all spec reviews approved -> `Designing`
- design review approved -> `Tasking`
- tasks review and OpenSpec validation approved -> `Implementing`
- PR opened -> `Code Review`
- CI and review approved -> `Ready to Merge`
- PR merged and OpenSpec archived -> `Done`
- any blocking ambiguity or failed gate -> `Blocked`

Use field discovery before edits. Do not hard-code field IDs unless the project handbook already provides stable IDs.

## Command Patterns

List items:

```bash
gh project item-list <project-number> --owner <owner> --format json
```

List fields:

```bash
gh project field-list <project-number> --owner <owner> --format json
```

Edit an item:

```bash
gh project item-edit --project-id <project-id> --id <item-id> --field-id <field-id> --single-select-option-id <option-id>
```

Create a draft item when no issue exists yet:

```bash
gh project item-create <project-number> --owner <owner> --title "<title>" --body "<body>" --format json
```

## Drift Rules

- Project item cannot be `Done` unless PR is merged and OpenSpec archive is complete.
- Project item cannot be `Implementing` unless tasks review and OpenSpec strict validation passed.
- Project item cannot be `Designing` unless every spec review is approved.
- Project item cannot be `Code Review` unless a PR exists and links the OpenSpec change.
```

- [ ] **Step 2: Create `project-status-map.md`**

Create `codex-sdd-delivery/references/project-status-map.md` with exactly this content:

```markdown
# Project Status Map

Use these statuses when the target GitHub Project supports them. If the Project has different names, map the nearest equivalent and record the mapping in the Project item or issue.

| Status | Meaning | Allowed Next Status |
| --- | --- | --- |
| Backlog | Not ready for Codex work | Ready, Blocked |
| Ready | Prioritized and eligible for intake | Specifying, Blocked |
| Specifying | Proposal is being created or reviewed | Spec Review, Blocked |
| Spec Review | Capability specs and independent reviews are in progress | Designing, Blocked |
| Designing | Technical design is being created or reviewed | Tasking, Blocked |
| Tasking | Tasks are being created, reviewed, and validated | Implementing, Blocked |
| Implementing | TDD implementation is in progress | Code Review, Blocked |
| Code Review | PR, CI, and code review are active | Ready to Merge, Implementing, Blocked |
| Ready to Merge | Required review and CI passed | Done, Blocked |
| Done | PR merged and OpenSpec archived | Backlog only for reopened work |
| Blocked | Cannot proceed without resolution | Previous non-blocked status after blocker clears |

## Required Evidence by Status

| Status | Evidence |
| --- | --- |
| Specifying | Linked issue, branch, OpenSpec change path |
| Spec Review | Proposal review approved |
| Designing | Every `reviews/specs/*.review.md` says `Decision: Approved` |
| Tasking | Design review approved |
| Implementing | Tasks review approved and OpenSpec strict validation passed |
| Code Review | PR URL and local verification evidence |
| Ready to Merge | CI, code review, and OpenSpec validation passed |
| Done | Merge commit or merged PR URL and OpenSpec archive confirmation |
```

- [ ] **Step 3: Verify Project references**

Run:

```bash
rg -n "gh project item-list|gh project field-list|gh project item-edit|Decision: Approved|Done" codex-sdd-delivery/references/github-project.md codex-sdd-delivery/references/project-status-map.md
```

Expected: command patterns and status evidence rules are present.

- [ ] **Step 4: Commit GitHub Project references**

Run:

```bash
git add codex-sdd-delivery/references/github-project.md codex-sdd-delivery/references/project-status-map.md
git commit -m "docs: add github project first delivery rules"
```

Expected: one commit containing only the Project references.

## Task 4: Write Branch and PR Rules

**Files:**
- Create: `codex-sdd-delivery/references/github-branch-pr.md`
- Create: `codex-sdd-delivery/references/pr-template.md`

- [ ] **Step 1: Create `github-branch-pr.md`**

Create `codex-sdd-delivery/references/github-branch-pr.md` with exactly this content:

```markdown
# GitHub Branch and PR Rules

## Branch Naming

Use one of:

```text
feature/<issue-number>-<short-slug>
bugfix/<issue-number>-<short-slug>
chore/<issue-number>-<short-slug>
```

OpenSpec change name should match the issue and branch slug:

```text
<issue-number>-<short-slug>
```

Example:

```text
Issue: #123 Add portfolio import
Branch: feature/123-portfolio-import
OpenSpec: openspec/changes/123-portfolio-import/
PR title: feat: add portfolio import
```

## Branch Creation

```bash
git fetch origin
git switch main
git pull --ff-only
git switch -c feature/<issue-number>-<short-slug>
```

If the repo uses a default branch other than `main`, use the repo default branch.

## Commit Rules

- Commit after each verified implementation slice.
- Do not mix unrelated refactors with feature work.
- Do not stage unrelated user changes.
- Use conventional commit prefixes: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`.

Pre-commit checks:

```bash
git diff --staged
git diff --staged | rg -i "password|secret|api_key|token" || true
```

## PR Creation

Always write the PR body to a file and use `--body-file`:

```bash
gh pr create --title "<type>: <summary>" --body-file /tmp/<change-name>-pr.md
```

Do not inline complex markdown in the shell command. Backticks and command substitution can corrupt PR bodies.

## Review Loop

```bash
gh pr view <pr-number> --json number,title,body,state,url,reviews
gh pr checks <pr-number>
gh pr status
```

Rules:

- Fix required review findings before merge.
- Push fixes before resolving review threads.
- Re-run OpenSpec validation and tests after review fixes.
- Update PR body when evidence changes.

## Merge and Cleanup

```bash
gh pr checks <pr-number>
gh pr merge <pr-number> --squash --delete-branch
openspec archive <change-name> --yes
```

Project item moves to Done only after merge and archive.
```

- [ ] **Step 2: Create `pr-template.md`**

Create `codex-sdd-delivery/references/pr-template.md` with exactly this content:

```markdown
# PR Template

Use this as the body for SDD delivery pull requests.

```markdown
## Source

- Project item: <project item URL or ID>
- Issue: <issue URL>
- Branch: <branch name>
- OpenSpec change: `openspec/changes/<change-name>/`

## Gate Evidence

- Proposal review: Approved
- Spec reviews:
  - `<capability>`: Approved in `openspec/changes/<change-name>/reviews/specs/<capability>.review.md`
- Design review: Approved
- Tasks review: Approved
- OpenSpec validation: `openspec validate <change-name> --type change --strict --no-interactive`

## Implementation Summary

- <change summary bullet>

## Verification

- <test command and result>
- <build/lint command and result>
- <manual or browser check when relevant>

## Review Response

- Code review findings addressed:
  - <finding summary and fix evidence>

## Project Update

- Status before PR: Implementing
- Status after PR open: Code Review
- Remaining status update after merge: Done after archive

## Risks and Follow-Up

- <known risk or "None">
```

When creating the PR body, replace angle-bracket fields with real values before running `gh pr create --body-file`.
```

- [ ] **Step 3: Verify branch and PR references**

Run:

```bash
rg -n "feature/<issue-number>|gh pr create|--body-file|openspec archive|Project item moves to Done" codex-sdd-delivery/references/github-branch-pr.md codex-sdd-delivery/references/pr-template.md
```

Expected: branch naming, PR body-file usage, archive, and Project Done rule are present.

- [ ] **Step 4: Commit Branch and PR references**

Run:

```bash
git add codex-sdd-delivery/references/github-branch-pr.md codex-sdd-delivery/references/pr-template.md
git commit -m "docs: add github branch and pr delivery rules"
```

Expected: one commit containing only branch and PR references.

## Task 5: Write OpenSpec CLI Rules

**Files:**
- Create: `codex-sdd-delivery/references/openspec-cli.md`

- [ ] **Step 1: Create `openspec-cli.md`**

Create `codex-sdd-delivery/references/openspec-cli.md` with exactly this content:

```markdown
# OpenSpec CLI Rules

OpenSpec CLI owns artifact creation instructions, status, validation, and archive.

## Required Version Check

```bash
openspec --version
```

Expected: command exists. Version `1.3.1` or newer is preferred because this workflow uses `openspec instructions`, `openspec status`, and `openspec validate`.

## Project Setup

```bash
openspec init --tools codex .
openspec update .
```

Use `openspec update --force .` only when generated instructions are stale and the repo owner agrees.

## Change Setup

```bash
openspec new change <change-name> --description "<short summary>"
openspec status --change <change-name>
```

The change name should match the GitHub issue and branch slug.

## Artifact Instructions

Run the relevant instruction command immediately before writing each artifact:

```bash
openspec instructions proposal --change <change-name>
openspec instructions specs --change <change-name>
openspec instructions design --change <change-name>
openspec instructions tasks --change <change-name>
```

Follow the output path printed by the CLI. Do not create artifact paths from memory when the CLI gives a path.

## Validation

Run validation before implementation, after implementation, before PR, and after review fixes:

```bash
openspec validate <change-name> --type change --strict --no-interactive
```

If validation fails, stop and fix the artifacts before continuing.

## Archive

After PR merge:

```bash
openspec archive <change-name> --yes
```

Project item can move to Done only after archive succeeds or the archive limitation is documented as a blocker.
```

- [ ] **Step 2: Verify OpenSpec commands**

Run:

```bash
rg -n "openspec init|openspec new change|openspec instructions proposal|openspec validate|openspec archive" codex-sdd-delivery/references/openspec-cli.md
```

Expected: required OpenSpec commands are present.

- [ ] **Step 3: Commit OpenSpec reference**

Run:

```bash
git add codex-sdd-delivery/references/openspec-cli.md
git commit -m "docs: add openspec cli delivery rules"
```

Expected: one commit containing only `openspec-cli.md`.

## Task 6: Write Skill Map

**Files:**
- Create: `codex-sdd-delivery/references/skill-map.md`

- [ ] **Step 1: Create `skill-map.md`**

Create `codex-sdd-delivery/references/skill-map.md` with exactly this content:

```markdown
# Skill Map

Use this map to select the right skill for each SDD delivery phase.

| Situation | Required Skills |
| --- | --- |
| Start of task or skill selection | `using-agent-skills` |
| GitHub issue, PR, CI, or Project work | `github` |
| Branching, commits, worktrees, merge hygiene | `git-workflow-and-versioning` |
| Vague requirement or product idea | `idea-refine`, `superpowers:brainstorming` |
| New feature, major change, or unclear requirements | `spec-driven-development`, `superpowers:brainstorming` |
| API or module boundary design | `api-and-interface-design` |
| Frontend or UI behavior | `frontend-ui-engineering` |
| Security, auth, permissions, secrets, privacy | `security-and-hardening` |
| Performance-sensitive behavior | `performance-optimization` |
| External framework or library decisions | `source-driven-development` |
| High-risk or unfamiliar decisions | `doubt-driven-development` |
| Task decomposition | `planning-and-task-breakdown`, `superpowers:writing-plans` |
| Implementation slice | `incremental-implementation`, `superpowers:test-driven-development` |
| Browser runtime verification | `browser-testing-with-devtools` |
| Failing tests or unexpected behavior | `debugging-and-error-recovery` |
| Code review | `code-review-and-quality` |
| CI/CD work | `ci-cd-and-automation` |
| Architecture decisions or public docs | `documentation-and-adrs` |
| Launch, rollout, or merge completion | `shipping-and-launch` |

## Rule

agent-skills select the engineering method. Superpowers enforce the hard gates. OpenSpec CLI owns the artifact state.
```

- [ ] **Step 2: Verify skill coverage**

Run:

```bash
rg -n "using-agent-skills|github|superpowers:brainstorming|superpowers:writing-plans|superpowers:test-driven-development|code-review-and-quality|shipping-and-launch" codex-sdd-delivery/references/skill-map.md
```

Expected: every major phase skill is represented.

- [ ] **Step 3: Commit skill map**

Run:

```bash
git add codex-sdd-delivery/references/skill-map.md
git commit -m "docs: add sdd delivery skill map"
```

Expected: one commit containing only `skill-map.md`.

## Task 7: Write Artifact Gates

**Files:**
- Create: `codex-sdd-delivery/references/artifact-gates.md`

- [ ] **Step 1: Create `artifact-gates.md`**

Create `codex-sdd-delivery/references/artifact-gates.md` with exactly this content:

```markdown
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
```

- [ ] **Step 2: Verify gate stop conditions**

Run:

```bash
rg -n "Passes when:|Stops when:|Decision: Approved|openspec validate|PR links" codex-sdd-delivery/references/artifact-gates.md
```

Expected: every gate has pass and stop language.

- [ ] **Step 3: Commit artifact gates**

Run:

```bash
git add codex-sdd-delivery/references/artifact-gates.md
git commit -m "docs: add sdd delivery artifact gates"
```

Expected: one commit containing only `artifact-gates.md`.

## Task 8: Write Per-Spec Review Template

**Files:**
- Create: `codex-sdd-delivery/references/spec-review-template.md`

- [ ] **Step 1: Create `spec-review-template.md`**

Create `codex-sdd-delivery/references/spec-review-template.md` with exactly this content:

```markdown
# Spec Review Template

Each capability spec requires one independent review file.

Spec path:

```text
openspec/changes/<change-name>/specs/<capability>/spec.md
```

Review path:

```text
openspec/changes/<change-name>/reviews/specs/<capability>.review.md
```

Do not place review files under `specs/`; OpenSpec may parse them as delta specs.

## Required Review File Content

```markdown
# Spec Review: <capability>

Decision: Changes Requested

## Source Links

- Project item: <project item URL or ID>
- Issue: <issue URL>
- Spec: `openspec/changes/<change-name>/specs/<capability>/spec.md`

## Required Findings

- [ ] Example finding format: clarify whether permission errors return `403` or `404`.

## Checks

- [ ] Covers linked GitHub issue acceptance criteria.
- [ ] Covers Project item scope.
- [ ] Requirements describe observable behavior.
- [ ] Every requirement has at least one `#### Scenario:`.
- [ ] Scenarios are testable.
- [ ] Failure and edge cases are covered.
- [ ] Security, privacy, and permission behavior are explicit when relevant.
- [ ] Compatibility, migration, removal, or rename behavior is explicit when relevant.
- [ ] No conflict with existing canonical specs.
- [ ] No ambiguous wording remains.

## Re-review Result

Decision: Approved
```

## Approval Rule

The review is approved only when:

- Required Findings is empty or every item is checked.
- Checks are complete.
- Re-review Result says `Decision: Approved`.

The design phase is blocked until every capability spec has an approved review file.
```

- [ ] **Step 2: Verify review template**

Run:

```bash
rg -n "reviews/specs|Decision: Changes Requested|Decision: Approved|Design phase is blocked" codex-sdd-delivery/references/spec-review-template.md
```

Expected: review path, initial decision, approval decision, and design block rule are present.

- [ ] **Step 3: Commit spec review template**

Run:

```bash
git add codex-sdd-delivery/references/spec-review-template.md
git commit -m "docs: add per spec review template"
```

Expected: one commit containing only `spec-review-template.md`.

## Task 9: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Review current README**

Run:

```bash
sed -n '1,220p' README.md
```

Expected: README still documents `codex-openspec-superpowers-github`.

- [ ] **Step 2: Add `codex-sdd-delivery` section**

Modify `README.md` by adding this section after the opening skill directory paragraph:

```markdown
## Recommended Workflow

For Project-first delivery, use `codex-sdd-delivery/`.

This skill coordinates:

- GitHub Project as the work queue and status source
- GitHub Issue as the discussion and acceptance record
- Git branch as the implementation sandbox
- OpenSpec CLI as the artifact and validation system
- agent-skills as phase-specific engineering guidance
- Superpowers as hard gates for brainstorming, planning, TDD, and verification
- GitHub PR as the final evidence packet

Use the older `codex-openspec-superpowers-github/` skill when you need the narrower OpenSpec + Superpowers + GitHub issue workflow without Project-first status management.
```

- [ ] **Step 3: Add invocation instructions**

Modify the Use section so it includes:

```markdown
For the Project-first workflow:

`$codex-sdd-delivery`

For the older issue/change workflow:

`$codex-openspec-superpowers-github`
```

- [ ] **Step 4: Verify README references**

Run:

```bash
rg -n "codex-sdd-delivery|Project-first|codex-openspec-superpowers-github" README.md
```

Expected: README documents both workflow skills and their difference.

- [ ] **Step 5: Commit README update**

Run:

```bash
git add README.md
git commit -m "docs: document project-first sdd delivery skill"
```

Expected: one commit containing only README changes. If README already has unrelated user edits, stage only the new hunks with an interactive patch or ask before proceeding.

## Task 10: Validate and Install the Skill

**Files:**
- Copy from: `codex-sdd-delivery/`
- Copy to: `/Users/mark/.skills/codex-sdd-delivery/`

- [ ] **Step 1: Validate repo copy**

Run:

```bash
python3 /Users/mark/.skills/.system/skill-creator/scripts/quick_validate.py /Users/mark/work/codex/codespec/codex-sdd-delivery
```

Expected: `Skill is valid!`

- [ ] **Step 2: Scan for incomplete markers**

Run:

```bash
python3 - <<'PY'
from pathlib import Path

markers = ["TO" + "DO", "TB" + "D", "fill" + " in", "implement" + " later"]
paths = [Path("codex-sdd-delivery"), Path("README.md")]

hits = []
for path in paths:
    files = path.rglob("*") if path.is_dir() else [path]
    for file in files:
        if file.is_file():
            text = file.read_text(encoding="utf-8")
            for marker in markers:
                if marker in text:
                    hits.append(f"{file}: contains {marker}")

if hits:
    print("\n".join(hits))
    raise SystemExit(1)

print("No incomplete markers found")
PY
```

Expected: `No incomplete markers found`.

- [ ] **Step 3: Install by copying a real directory**

Run:

```bash
rsync -a /Users/mark/work/codex/codespec/codex-sdd-delivery/ /Users/mark/.skills/codex-sdd-delivery/
```

Expected: installed skill directory exists as a real directory, not a child symlink.

- [ ] **Step 4: Validate installed copy**

Run:

```bash
python3 /Users/mark/.skills/.system/skill-creator/scripts/quick_validate.py /Users/mark/.skills/codex-sdd-delivery
```

Expected: `Skill is valid!`

- [ ] **Step 5: Confirm repo and installed copies match**

Run:

```bash
diff -rq /Users/mark/work/codex/codespec/codex-sdd-delivery /Users/mark/.skills/codex-sdd-delivery
```

Expected: no output.

- [ ] **Step 6: Commit install-ready state**

Run:

```bash
git status --short
git add codex-sdd-delivery README.md
git commit -m "feat: add project-first sdd delivery workflow skill"
```

Expected: commit contains only intended `codex-sdd-delivery` files and README updates. Do not include unrelated existing modifications.

## Task 11: Self-Review the Implemented Skill

**Files:**
- Inspect: `codex-sdd-delivery/SKILL.md`
- Inspect: `codex-sdd-delivery/references/*.md`
- Inspect: `README.md`

- [ ] **Step 1: Check spec coverage**

Run:

```bash
rg -n "GitHub Project|GitHub Issue|branch|OpenSpec|agent-skills|Superpowers|per-spec|Decision: Approved|gh pr|openspec archive" codex-sdd-delivery README.md
```

Expected: all requested domains appear in the skill or README.

- [ ] **Step 2: Check gate ordering**

Run:

```bash
rg -n "Do not write implementation code|Design phase is blocked|OpenSpec strict validation|Project item can move to Done" codex-sdd-delivery
```

Expected: hard gate wording exists for implementation, design, validation, and Done state.

- [ ] **Step 3: Check skill references**

Run:

```bash
rg -n "using-agent-skills|spec-driven-development|planning-and-task-breakdown|incremental-implementation|code-review-and-quality|superpowers:brainstorming|superpowers:writing-plans|superpowers:test-driven-development" codex-sdd-delivery
```

Expected: both agent-skills and Superpowers are mapped to workflow phases.

- [ ] **Step 4: Check OpenSpec commands**

Run:

```bash
rg -n "openspec init|openspec update|openspec new change|openspec status|openspec instructions|openspec validate|openspec archive" codex-sdd-delivery
```

Expected: all OpenSpec commands required by this workflow appear.

- [ ] **Step 5: Final status**

Run:

```bash
git status --short --branch
```

Expected: no unintended unstaged changes from implementing this plan. Existing unrelated changes may remain if they predated the implementation and were intentionally ignored.

## Deferred Automation Candidate: Add a Delivery Checker

Do not create this in the first pass. Add it only after the document-only skill has been used on real work and repeated failure patterns are known.

Future file:

- Create: `codex-sdd-delivery/scripts/check_sdd_delivery.py`

Future checks:

- Project item link exists.
- Issue link exists.
- Branch name matches issue and OpenSpec change.
- `proposal.md`, `design.md`, and `tasks.md` exist.
- Every `specs/<capability>/spec.md` has matching `reviews/specs/<capability>.review.md`.
- Every spec review says `Decision: Approved`.
- `openspec validate <change-name> --type change --strict --no-interactive` passes.
- PR body includes Project, Issue, OpenSpec, spec review, tests, and risks.

## Checkpoints

### Checkpoint 1: Skill Shell

- [ ] Task 1 complete.
- [ ] `quick_validate.py` passes.
- [ ] `SKILL.md` names all hard gates.

### Checkpoint 2: Delivery Workflow

- [ ] Tasks 2-8 complete.
- [ ] GitHub Project-first workflow is represented.
- [ ] OpenSpec CLI workflow is represented.
- [ ] Every spec has independent review mechanics.
- [ ] Skill mapping covers agent-skills and Superpowers.

### Checkpoint 3: Installation

- [ ] Tasks 9-10 complete.
- [ ] README explains both old and new workflow skills.
- [ ] Repo and installed copies match.
- [ ] Installed copy validates.

### Checkpoint 4: Final Review

- [ ] Task 11 complete.
- [ ] No incomplete markers remain.
- [ ] Existing unrelated repo modifications are not staged.

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Skill becomes too long | Codex may not read the whole workflow | Keep `SKILL.md` short and place detailed content in one-level references |
| GitHub Project field IDs vary | Project edits can fail | Always run `gh project field-list` and avoid hard-coded IDs |
| Spec review becomes ceremonial | Bad specs pass into design | Require one review file per capability and block design until `Decision: Approved` |
| PR body is corrupted by shell quoting | Evidence packet becomes unreadable | Always use `gh pr create --body-file` or `gh pr edit --body-file` |
| Existing dirty worktree causes accidental staging | User changes could be committed unintentionally | Use explicit file paths in `git add`; inspect `git status --short` before every commit |
| OpenSpec command behavior changes | Workflow instructions drift | Validate with `openspec --version` and `openspec --help`; update `openspec-cli.md` when CLI changes |

## Implementation Defaults

- First implementation pass creates `codex-sdd-delivery` and updates README only. It does not migrate or rewrite existing `codex-openspec-superpowers-github` content.
- Install `codex-sdd-delivery` during Task 10 after the repo copy validates.
- Keep GitHub Project status names generic. Project-specific field IDs belong in project-local notes, not in this reusable skill.

## Self-Review

- Spec coverage: This plan covers strong gate workflow, GitHub Project-first intake, GitHub issue linkage, branch naming, PR evidence, OpenSpec CLI artifacts, agent-skills mapping, Superpowers gates, per-spec review, validation, install, and final review.
- Placeholder scan: The plan avoids unresolved placeholder markers from the writing-plans skill. Angle-bracket values are intentional template variables inside the generated skill references.
- Type and name consistency: The skill name is consistently `codex-sdd-delivery`; Project-first status and OpenSpec change terms are consistent across tasks.
- Scope check: The first pass is document-only plus installation. The automated checker is explicitly deferred until after real workflow usage.
