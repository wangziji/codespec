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
| Independent artifact review | reviewer agent, `code-review-and-quality`, `doubt-driven-development` when risk is high |
| Implementation slice | `incremental-implementation`, `superpowers:test-driven-development` |
| Browser runtime verification | `browser-testing-with-devtools` |
| Failing tests or unexpected behavior | `debugging-and-error-recovery` |
| Code review | `code-review-and-quality` |
| CI/CD work | `ci-cd-and-automation` |
| Architecture decisions or public docs | `documentation-and-adrs` |
| Launch, rollout, or merge completion | `shipping-and-launch` |

## Rule

agent-skills select the engineering method. Superpowers enforce the hard gates. OpenSpec CLI owns the artifact state.
