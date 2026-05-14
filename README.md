# codespec

This repo contains a Codex workflow skill that combines:

- OpenSpec (artifact-first change planning)
- Superpowers (brainstorming, planning, TDD discipline)
- GitHub (issue intake + PR publication)

Skill directory: `codex-openspec-superpowers-github/`.

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

## Install

1. Install OpenSpec (Node.js 20.19+ recommended):

```bash
npm install -g @fission-ai/openspec@latest
```

2. Ensure GitHub tooling is authenticated (one of):

```bash
gh auth status
```

3. Make the skill discoverable to Codex.

Recommended: clone this repo directly into your skills directory as a real folder (avoid symlinks).

```bash
mkdir -p ~/.skills
git clone git@github.com:wangziji/codespec.git ~/.skills/codex-openspec-superpowers-github
```

If you already have the repo somewhere else and want to copy just the skill folder:

```bash
mkdir -p ~/.skills
rsync -a ./codex-openspec-superpowers-github/ ~/.skills/codex-openspec-superpowers-github/
```

## Use

In Codex, invoke:

For the Project-first workflow:

`$codex-sdd-delivery`

For the older issue/change workflow:

`$codex-openspec-superpowers-github`

Then follow the workflow gates in:

- `codex-sdd-delivery/SKILL.md`
- `codex-sdd-delivery/references/workflow.md`
- `codex-sdd-delivery/references/artifact-gates.md`
- `codex-sdd-delivery/references/spec-review-template.md`
- `codex-openspec-superpowers-github/SKILL.md`
- `codex-openspec-superpowers-github/references/workflow.md`
- `codex-openspec-superpowers-github/references/review-gates.md`

The skill uses the OpenSpec CLI for change setup and validation:

```bash
openspec new change <change-name> --description "<short summary>"
openspec instructions proposal --change <change-name>
openspec instructions specs --change <change-name>
openspec instructions design --change <change-name>
openspec instructions tasks --change <change-name>
openspec validate <change-name> --type change --strict --no-interactive
```

## What It Enforces

- OpenSpec artifacts first: `proposal.md`, delta `specs/`, `design.md`, `tasks.md`
- Review + fix gates between proposal/specs, design, tasks, and code review
- TDD for implementation work
- PR body includes evidence and links to OpenSpec change artifacts
