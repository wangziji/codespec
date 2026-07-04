---
name: codex-sdd-delivery
description: Use when Codex should run a full GitHub Project-first spec-driven delivery workflow with OpenSpec CLI, GitHub issues, branches, PRs, agent-skills, Superpowers gates, per-spec reviews, validation, and archive
---

# Codex SDD Delivery

## Core Rule

Do not write implementation code until GitHub intake is linked, OpenSpec proposal is reviewed, every capability spec has an independent approved review, design is reviewed, tasks are reviewed, OpenSpec strict validation passes, and the working branch is linked to the tracked GitHub issue or Project item.

## Required Stage Skills

These skills are hard gates. Do not skip, substitute, collapse, or treat them as optional guidance.

- Proposal, specs, and design gates MUST use `superpowers:brainstorming`.
- Tasks gate MUST use `superpowers:writing-plans`.
- Implementation gate MUST use `superpowers:subagent-driven-development`.
- Code review gate MUST use `code-review-and-quality`.

## Required Document Language

All workflow documents MUST be written in Chinese. Do not switch the narrative language to English.

- `proposal.md` MUST be written in Chinese.
- Every capability `spec.md` MUST be written in Chinese.
- `design.md` MUST be written in Chinese.
- `tasks.md` MUST be written in Chinese.
- Review artifacts such as `reviews/specs/*.review.md` MUST be written in Chinese.
- PR evidence and review summaries for this workflow MUST be written in Chinese.

Literal code, shell commands, configuration keys, protocol names, API field names, and other identifiers may remain in their original language when translation would reduce accuracy.

## Required Execution Discipline

These rules are hard gates. Treat them as workflow constraints, not style advice.

- Think before coding: state assumptions explicitly, surface meaningful tradeoffs, and stop for clarification when ambiguity would change scope or behavior.
- Simplicity first: choose the minimum solution that satisfies the approved proposal, specs, design, and tasks. Do not add speculative flexibility, extra features, or single-use abstractions.
- Surgical changes: touch only files and lines that trace directly to the requested outcome. Remove only the dead code or imports created by your own change.
- Goal-driven execution: define a concrete verification target for every non-trivial step, then loop until the target is checked with tests, validation, review, or other direct evidence.

## Required Reading

Before starting work, read these files in order:

1. `references/workflow.md`
2. `references/github-project.md`
3. `references/github-branch-pr.md`
4. `references/openspec-cli.md`
5. `references/codegraph.md`
6. `references/skill-map.md`
7. `references/artifact-gates.md`
8. `references/spec-review-template.md`
9. `references/reviewer-agents.md`
10. `references/pr-template.md`
11. `references/project-status-map.md`

## Operating Model

- GitHub Project is the work queue and status source.
- GitHub Issue records discussion, scope, and acceptance criteria.
- Git branch isolates implementation.
- OpenSpec is the artifact contract.
- CodeGraph is the required code discovery and code search system after project startup.
- Per-spec reviews are mandatory gates, one review per capability spec.
- Independent reviewer agents may perform proposal, spec, design, tasks, and code review gates, but reviewer agents must not author or modify the artifact they review.
- agent-skills provide phase-specific engineering methods.
- Superpowers enforce hard gates for brainstorming, planning, implementation orchestration, and verification.
- GitHub PR is the delivery evidence packet.

## Stop Conditions

Stop and repair before continuing when:

- GitHub Project item, issue, branch, OpenSpec change, or PR links are missing.
- CodeGraph is not initialized or its index is stale at project startup.
- Code search, symbol lookup, impact analysis, or affected-test discovery uses raw grep/find/read sweeps before CodeGraph.
- Proposal, specs, or design work proceeds without `superpowers:brainstorming`.
- Tasks work proceeds without `superpowers:writing-plans`.
- Implementation proceeds without `superpowers:subagent-driven-development`.
- Code review proceeds without `code-review-and-quality`.
- Any required workflow document is written primarily in English instead of Chinese.
- Assumptions that affect behavior, scope, or interface are left implicit.
- The chosen solution is more complex than required by the approved artifacts.
- Changes spill into unrelated files, formatting, refactors, or cleanup outside the requested scope.
- A non-trivial phase proceeds without explicit verification goals or without recorded verification evidence.
- Any proposal, spec, design, tasks, validation, implementation, review, or PR gate fails.
- Any spec review is missing or not approved.
- A reviewer agent edits the reviewed artifact or approves its own work.
- OpenSpec validation fails.
- Tests, build, lint, CI, or code review fail.
- Project status says a later phase than the artifacts support.

## Completion Rule

Work is complete only when the PR contains Project, issue, OpenSpec, test, review, and risk evidence; CI/reviews are resolved; the Project item status is current; and the OpenSpec change is archived after merge.
