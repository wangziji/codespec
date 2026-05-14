# OpenSpec CLI Rules

OpenSpec CLI owns artifact creation instructions, status, validation, and archive.

## Required Version Check

```bash
openspec --version
```

Expected: command exists. Version `1.3.1` or newer is preferred because this workflow uses `openspec instructions`, `openspec status`, and `openspec validate`.

## Project Setup

```bash
openspec init --tools codex .
openspec update .
```

Use `openspec update --force .` only when generated instructions are stale and the repo owner agrees.

## Change Setup

```bash
openspec new change <change-name> --description "<short summary>"
openspec status --change <change-name>
```

The change name should match the GitHub issue and branch slug.

## Artifact Instructions

Run the relevant instruction command immediately before writing each artifact:

```bash
openspec instructions proposal --change <change-name>
openspec instructions specs --change <change-name>
openspec instructions design --change <change-name>
openspec instructions tasks --change <change-name>
```

Follow the output path printed by the CLI. Do not create artifact paths from memory when the CLI gives a path.

## Validation

Run validation before implementation, after implementation, before PR, and after review fixes:

```bash
openspec validate <change-name> --type change --strict --no-interactive
```

If validation fails, stop and fix the artifacts before continuing.

## Archive

After PR merge:

```bash
openspec archive <change-name> --yes
```

Project item can move to Done only after archive succeeds or the archive limitation is documented as a blocker.
