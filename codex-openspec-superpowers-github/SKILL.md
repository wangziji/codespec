---
name: codex-openspec-superpowers-github
description: Use when a Codex feature or bugfix request mentions OpenSpec CLI, spec-first development, GitHub issues, Superpowers planning or TDD, code review gates, or PR publication
---

# Codex OpenSpec Superpowers GitHub

## Overview

Run a CLI-first spec-driven development loop that combines GitHub issue intake, OpenSpec change artifacts, Superpowers brainstorming/planning/TDD discipline, Codex implementation, review repair, and PR publication.

Core principle: do not write product code until proposal, specs, design, and tasks have each been created, reviewed, and repaired.

## Required Sub-Skills

- **REQUIRED:** Use `github` or `github:github` when the request names a GitHub issue, PR, repository, or feature ticket.
- **REQUIRED:** Use `superpowers:brainstorming` to strengthen proposal/specs, then design.
- **REQUIRED:** Use `superpowers:writing-plans` to refine `tasks.md`.
- **REQUIRED:** Use `superpowers:test-driven-development` before feature or bugfix code.
- **REQUIRED:** Use the repo's code-review workflow, `code-review`, or Codex review stance before publishing the PR.

If a sub-skill is unavailable, state that and follow the same gate manually.

## Required Reading

Before starting work, read:

- `references/workflow.md` for the exact end-to-end sequence.
- `references/openspec-artifacts.md` when creating or repairing artifacts.
- `references/review-gates.md` before each review/fix gate.

## Gate Summary

| Phase | Do |
| --- | --- |
| Intake | Read user request or GitHub issue; identify feature vs bugfix. |
| Branch | Create `codex/feature-<slug>` or `codex/bugfix-<slug>`. |
| OpenSpec setup | Use `openspec --version`, `openspec init --tools codex .`, and `openspec update`. |
| Change | Use `openspec new change <name>` and `openspec status --change <name>`. |
| Artifacts | Use `openspec instructions <artifact> --change <name>` before writing each artifact. |
| Proposal/spec review | Review proposal and specs, then fix all findings. |
| Design review | Improve design, review it, then fix all findings. |
| Task plan | Use writing-plans; review tasks for traceability and TDD slices. |
| Implementation | Use TDD task by task; keep `tasks.md` checkboxes current. |
| Review repair | Run `openspec validate <name> --type change --strict --no-interactive`, code review, and tests. |
| PR | Push branch and open PR with artifact links, test evidence, and review summary. |

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Using slash commands and immediately coding | Stop after artifacts; run the proposal/spec/design/task review loops first. |
| Creating OpenSpec files from memory | Run `openspec instructions <artifact> --change <name>` and follow the CLI output. |
| Treating `tasks.md` as a vague checklist | Rewrite tasks into TDD-sized, verifiable slices. |
| Reviewing only code | Review artifacts before code and OpenSpec compliance after code. |
| Losing GitHub issue context | Link the issue in proposal and PR; carry acceptance criteria into specs and tasks. |
| Updating code but not specs | Sync design/spec/task artifacts when implementation changes scope or behavior. |

## Resources

- `references/workflow.md`: mandatory execution order.
- `references/openspec-artifacts.md`: minimum artifact layout and content.
- `references/review-gates.md`: review checklists and repair gates.
