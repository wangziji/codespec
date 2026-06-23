# Skill Map

Use this map to select the right skill for each SDD delivery phase.

| Situation | Required Skills |
| --- | --- |
| Start of task or skill selection | `using-agent-skills` |
| Project startup and code graph initialization | `codegraph --version`, `codegraph status .`, `codegraph init -i .` |
| Code search, symbol lookup, impact analysis, affected tests | CodeGraph CLI or MCP tools before raw grep/find/read sweeps |
| GitHub issue, PR, CI, or Project work | `github` |
| Branching, commits, worktrees, merge hygiene | `git-workflow-and-versioning` |
| Proposal, specs, or design | **REQUIRED HARD GATE:** `superpowers:brainstorming` |
| Vague requirement or product idea | `idea-refine`, `superpowers:brainstorming` |
| New feature, major change, or unclear requirements | `spec-driven-development`, `superpowers:brainstorming` |
| API or module boundary design | `api-and-interface-design` |
| Frontend or UI behavior | `frontend-ui-engineering` |
| Security, auth, permissions, secrets, privacy | `security-and-hardening` |
| Performance-sensitive behavior | `performance-optimization` |
| External framework or library decisions | `source-driven-development` |
| High-risk or unfamiliar decisions | `doubt-driven-development` |
| Task decomposition | `planning-and-task-breakdown`, **REQUIRED HARD GATE:** `superpowers:writing-plans` |
| Independent artifact review | reviewer agent, `code-review-and-quality`, `doubt-driven-development` when risk is high |
| Implementation plan execution | **REQUIRED HARD GATE:** `superpowers:subagent-driven-development` |
| Implementation slice | `incremental-implementation`, `superpowers:test-driven-development` |
| Browser runtime verification | `browser-testing-with-devtools` |
| Failing tests or unexpected behavior | `debugging-and-error-recovery` |
| Code review | **REQUIRED HARD GATE:** `code-review-and-quality` |
| CI/CD work | `ci-cd-and-automation` |
| Architecture decisions or public docs | `documentation-and-adrs` |
| Launch, rollout, or merge completion | `shipping-and-launch` |

## Rule

agent-skills select the engineering method. The required Superpowers and code review skills are hard gates, not suggestions. OpenSpec CLI owns the artifact state.
