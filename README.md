# codespec

This repo contains a Codex workflow skill that combines:

- OpenSpec (artifact-first change planning)
- Superpowers (brainstorming, planning, TDD discipline)
- GitHub (issue intake + PR publication)

Skill directory: `codex-openspec-superpowers-github/`.

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

`$codex-openspec-superpowers-github`

Then follow the workflow gates in:

- `codex-openspec-superpowers-github/SKILL.md`
- `codex-openspec-superpowers-github/references/workflow.md`
- `codex-openspec-superpowers-github/references/review-gates.md`

## What It Enforces

- OpenSpec artifacts first: `proposal.md`, delta `specs/`, `design.md`, `tasks.md`
- Review + fix gates between proposal/specs, design, tasks, and code review
- TDD for implementation work
- PR body includes evidence and links to OpenSpec change artifacts
