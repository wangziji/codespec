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
   - Verify `openspec --version`; if unavailable, install or ask the user to install `@fission-ai/openspec`.
   - If `openspec/` is missing, run `openspec init --tools codex .` unless the repo has a different convention.
   - If OpenSpec is present but generated guidance is stale, run `openspec update .` or `openspec update --force .`.
   - Do not create OpenSpec artifacts from memory when the CLI can provide instructions.

4. Create the OpenSpec change
   - Run `openspec new change <change-name> --description "<short summary>"`.
   - Run `openspec status --change <change-name>` to confirm artifact order and blockers.
   - Use the generated `openspec/changes/<change-name>/` path as the single source of truth.

5. Proposal and specs loop
   - Run `openspec instructions proposal --change <change-name>` and write the proposal to the output path named by the CLI.
   - Use `superpowers:brainstorming` to improve proposal from user goals, issue evidence, and repo context.
   - Run `openspec instructions specs --change <change-name>` and write specs to the output paths named by the CLI.
   - Review proposal and specs with `review-gates.md`.
   - Fix every actionable review issue before touching design.

6. Design loop
   - Run `openspec instructions design --change <change-name>` and write design to the output path named by the CLI.
   - Use `superpowers:brainstorming` to improve design.
   - Review architecture, data flow, error handling, migrations, security, rollout, observability, and test strategy.
   - Fix every actionable review issue before refining tasks.

7. Tasks loop
   - Run `openspec instructions tasks --change <change-name>` and write tasks to the output path named by the CLI.
   - Use `superpowers:writing-plans` to make tasks concrete, ordered, and test-first.
   - Review tasks for traceability and TDD-sized slices.
   - Fix task review issues before implementation.
   - Run `openspec status --change <change-name>` and `openspec validate <change-name> --type change --strict --no-interactive`; fix OpenSpec validation issues before implementation.

8. Implement with TDD
   - Use `superpowers:test-driven-development`.
   - For each behavior: write failing test, verify RED, implement minimally, verify GREEN, refactor, then check off the task.
   - Do not check off a task without test or verification evidence.

9. Code review and repair
   - Run tests, linters, type checks, and app-specific verification.
   - Run `openspec validate <change-name> --type change --strict --no-interactive`.
   - Perform code review with findings first, including OpenSpec compliance.
   - Fix findings, rerun affected tests, and update artifacts if implementation changed design or scope.

10. Publish PR
    - Push the branch.
    - Open a GitHub PR.
    - PR body must include source issue/user request, OpenSpec change path, summary, test evidence, review/fix summary, and remaining risks.
