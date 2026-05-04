# Workflow

Follow this sequence exactly. Do not skip, merge, or reorder review and repair gates.

1. Confirm context
   - Inspect repo status, branch, remotes, project docs, and recent commits.
   - If GitHub issue input is provided, fetch issue body, comments, labels, and acceptance criteria using the GitHub skill or `gh`.
   - If the request is ambiguous, ask one high-signal question before branching.

2. Create branch
   - Use `codex/feature-<issue-or-topic-slug>` for features.
   - Use `codex/bugfix-<issue-or-topic-slug>` for bugs.
   - Do not overwrite or reset user changes. If the worktree is dirty, identify unrelated changes and work around them.

3. Prepare OpenSpec
   - Verify `openspec --version`; if unavailable, tell the user to install `@fission-ai/openspec` or ask before installing globally.
   - If `openspec/` is missing, run `openspec init --tools codex` unless the repo has a different convention.
   - If OpenSpec is present but generated guidance is stale, run `openspec update`.
   - Prefer generated OpenSpec Codex skills/commands. If unavailable, create files directly using `openspec/changes/<change>/`.

4. Create base artifacts
   - Create `proposal.md`.
   - Create delta specs under `specs/<domain>/spec.md`.
   - Create `design.md`.
   - Create `tasks.md`.
   - Use `openspec-artifacts.md` for minimum shape.

5. Proposal and specs loop
   - Use `superpowers:brainstorming` to improve proposal and specs from user goals, issue evidence, and repo context.
   - Review both files with `review-gates.md`.
   - Fix every actionable review issue before touching design.

6. Design loop
   - Use `superpowers:brainstorming` to improve design.
   - Review architecture, data flow, error handling, migrations, security, rollout, observability, and test strategy.
   - Fix every actionable review issue before refining tasks.

7. Tasks loop
   - Use `superpowers:writing-plans` to make tasks concrete, ordered, and test-first.
   - Review tasks for traceability and TDD-sized slices.
   - Fix task review issues before implementation.

8. Implement with TDD
   - Use `superpowers:test-driven-development`.
   - For each behavior: write failing test, verify RED, implement minimally, verify GREEN, refactor, then check off the task.
   - Do not check off a task without test or verification evidence.

9. Code review and repair
   - Run tests, linters, type checks, and app-specific verification.
   - Perform code review with findings first, including OpenSpec compliance.
   - Fix findings, rerun affected tests, and update artifacts if implementation changed design or scope.

10. Publish PR
    - Push the branch.
    - Open a GitHub PR.
    - PR body must include source issue/user request, OpenSpec change path, summary, test evidence, review/fix summary, and remaining risks.
