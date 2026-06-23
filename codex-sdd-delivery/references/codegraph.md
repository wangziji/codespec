# CodeGraph

CodeGraph is the required code discovery and code search system for SDD delivery work after project startup.

## Installation

Install CodeGraph before using this workflow:

```bash
npm i -g @colbymchenry/codegraph@latest
codegraph --version
```

If npm is unavailable, use the installer from the upstream project documentation.

## Startup Gate

Run this at the start of every project session before selecting or implementing work:

```bash
codegraph status .
```

If the project is not initialized or the index is missing, run:

```bash
codegraph init -i .
```

If CodeGraph reports a stale or pending index, run:

```bash
codegraph sync .
codegraph status .
```

The workflow may continue only when `codegraph status .` reports the index is up to date.

## Required Code Retrieval

Use CodeGraph for code search and discovery:

```bash
codegraph files --path . --format tree
codegraph files --path . --filter <directory> --format flat
codegraph query --path . "<symbol-or-search-text>"
codegraph callers --path . <symbol>
codegraph callees --path . <symbol>
codegraph impact --path . <symbol>
codegraph affected --path . <changed-files>
```

Raw `rg`, `find`, `grep`, `ls`, and direct file reads are still allowed for:

- Non-code artifacts, such as OpenSpec files, skill markdown, README files, Git metadata, and generated review notes.
- Verifying exact file contents after CodeGraph identifies the relevant code file.
- Cases where CodeGraph cannot parse or index the target file type.
- Diagnosing CodeGraph installation, status, or indexing failures.

When bypassing CodeGraph for code retrieval, record why the bypass was necessary.

## SDD Usage

- During requirements and design work, use CodeGraph to discover existing implementation boundaries before proposing changes.
- During task planning, use `codegraph impact` and `codegraph affected` to identify likely implementation files and tests.
- During implementation, use CodeGraph queries before opening broad code areas.
- During code review, use CodeGraph impact and caller/callee queries to validate blast radius.

## Stop Conditions

Stop the workflow when:

- `codegraph --version` is unavailable.
- `codegraph status .` does not report an up-to-date index and `codegraph init -i .` or `codegraph sync .` cannot repair it.
- Code search or impact analysis was done with raw grep/find/read sweeps before CodeGraph without a recorded exception.
- Reviewer or implementation evidence omits CodeGraph status for code-changing work.
