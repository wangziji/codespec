# OpenSpec Artifact Reference

Use this when running OpenSpec CLI commands or repairing incomplete artifacts.

## Project Setup

OpenSpec currently expects Node.js 20.19.0 or newer. Typical setup:

```bash
npm install -g @fission-ai/openspec@latest
openspec --version
openspec init --tools codex .
```

If the repo already has OpenSpec, prefer:

```bash
openspec update
```

For expanded OpenSpec workflows, run `openspec config profile`, select the needed workflows, then `openspec update`.

## CLI Workflow

Create and drive changes through the CLI:

```bash
openspec new change <change-name> --description "<short summary>"
openspec status --change <change-name>
openspec instructions proposal --change <change-name>
openspec instructions specs --change <change-name>
openspec instructions design --change <change-name>
openspec instructions tasks --change <change-name>
openspec validate <change-name> --type change --strict --no-interactive
```

Use `openspec instructions <artifact> --change <change-name>` immediately before writing each artifact. The command prints dependencies, output paths, formatting rules, templates, unlocks, and blockers.

Use `openspec status --change <change-name>` after each artifact to confirm the expected progression:

```text
proposal -> design + specs -> tasks
```

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

- Initialize or refresh: `openspec init --tools codex .`, `openspec update .`, `openspec update --force .`.
- Create change: `openspec new change <change-name> --description "<summary>"`.
- Inspect: `openspec list`, `openspec list --specs`, `openspec show <item> --type change`, `openspec status --change <change-name>`.
- Generate instructions: `openspec instructions <proposal|specs|design|tasks> --change <change-name>`.
- Validate: `openspec validate <change-name> --type change --strict --no-interactive`.
- Archive completed changes: `openspec archive <change-name> --yes`.

This skill intentionally adds stricter review gates between OpenSpec artifact creation and implementation.
