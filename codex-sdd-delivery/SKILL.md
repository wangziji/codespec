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
8. `references/reviewer-agents.md`
9. `references/pr-template.md`
10. `references/project-status-map.md`

## Operating Model

- GitHub Project is the work queue and status source.
- GitHub Issue records discussion, scope, and acceptance criteria.
- Git branch isolates implementation.
- OpenSpec is the artifact contract.
- Per-spec reviews are mandatory gates, one review per capability spec.
- Independent reviewer agents may perform proposal, spec, design, tasks, and code review gates, but reviewer agents must not author or modify the artifact they review.
- agent-skills provide phase-specific engineering methods.
- Superpowers enforce hard gates for brainstorming, planning, TDD, and verification.
- GitHub PR is the delivery evidence packet.

## Stop Conditions

Stop and repair before continuing when:

- GitHub Project item, issue, branch, OpenSpec change, or PR links are missing.
- Any proposal, spec, design, tasks, validation, implementation, review, or PR gate fails.
- Any spec review is missing or not approved.
- A reviewer agent edits the reviewed artifact or approves its own work.
- OpenSpec validation fails.
- Tests, build, lint, CI, or code review fail.
- Project status says a later phase than the artifacts support.

## Completion Rule

Work is complete only when the PR contains Project, issue, OpenSpec, test, review, and risk evidence; CI/reviews are resolved; the Project item status is current; and the OpenSpec change is archived after merge.
