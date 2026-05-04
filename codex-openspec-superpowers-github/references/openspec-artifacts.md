# OpenSpec Artifact Reference

Use this when OpenSpec generated skills or slash commands are unavailable, or when repairing incomplete artifacts.

## Project Setup

OpenSpec currently expects Node.js 20.19.0 or newer. Typical setup:

```bash
npm install -g @fission-ai/openspec@latest
openspec init --tools codex
```

If the repo already has OpenSpec, prefer:

```bash
openspec update
```

For expanded OpenSpec workflows, run `openspec config profile`, select the needed workflows, then `openspec update`.

## Standard Layout

```text
openspec/
  specs/
    <domain>/
      spec.md
  changes/
    <change-name>/
      proposal.md
      design.md
      tasks.md
      specs/
        <domain>/
          spec.md
```

## Artifact Minimums

`proposal.md`:

- Problem statement and goal.
- Source issue or user request link.
- In scope and out of scope.
- Acceptance criteria.
- Affected users, systems, APIs, jobs, data, and risks.

Delta `specs/<domain>/spec.md`:

- Requirements written as observable behavior.
- Scenario names and Given/When/Then style checks where useful.
- ADDED, MODIFIED, REMOVED, or RENAMED sections when the repo uses OpenSpec deltas.
- Explicit non-functional expectations if they affect implementation.

`design.md`:

- Current-state summary from code inspection.
- Proposed architecture and module boundaries.
- Data flow and API/contracts.
- Error handling, validation, permissions, migrations, rollout, and observability.
- Test strategy mapped to specs.
- Alternatives considered and why rejected.

`tasks.md`:

- Ordered tasks with checkboxes.
- Each implementation task has an expected RED test first.
- Verification commands or evidence per task group.
- Review and artifact-sync tasks before PR.

## OpenSpec Command Mapping

- Quick path: `/opsx:propose <change>` creates planning artifacts, then `/opsx:apply` implements.
- Controlled path: `/opsx:new <change>`, `/opsx:continue`, or `/opsx:ff` creates artifacts before implementation.
- Verification path: `/opsx:verify <change>` checks implementation against artifacts when available.

This skill intentionally adds stricter review gates between OpenSpec artifact creation and implementation.
