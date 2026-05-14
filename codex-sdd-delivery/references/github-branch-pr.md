# GitHub Branch and PR Rules

## Branch Naming

Use one of:

```text
feature/<issue-number>-<short-slug>
bugfix/<issue-number>-<short-slug>
chore/<issue-number>-<short-slug>
```

OpenSpec change name should match the issue and branch slug:

```text
<issue-number>-<short-slug>
```

Example:

```text
Issue: #123 Add portfolio import
Branch: feature/123-portfolio-import
OpenSpec: openspec/changes/123-portfolio-import/
PR title: feat: add portfolio import
```

## Branch Creation

```bash
git fetch origin
git switch <default-branch>
git pull --ff-only
git switch -c feature/<issue-number>-<short-slug>
```

Use the repository default branch, such as `main` or `master`, for `<default-branch>`.

## Commit Rules

- Commit after each verified implementation slice.
- Do not mix unrelated refactors with feature work.
- Do not stage unrelated user changes.
- Use conventional commit prefixes: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`.

Pre-commit checks:

```bash
git diff --staged
git diff --staged | rg -i "password|secret|api_key|token" || true
```

## PR Creation

Always write the PR body to a file and use `--body-file`:

```bash
gh pr create --title "<type>: <summary>" --body-file /tmp/<change-name>-pr.md
```

Do not inline complex markdown in the shell command. Backticks and command substitution can corrupt PR bodies.

## Review Loop

```bash
gh pr view <pr-number> --json number,title,body,state,url,reviews
gh pr checks <pr-number>
gh pr status
```

Rules:

- Fix required review findings before merge.
- Push fixes before resolving review threads.
- Re-run OpenSpec validation and tests after review fixes.
- Update PR body when evidence changes.

## Merge and Cleanup

```bash
gh pr checks <pr-number>
gh pr merge <pr-number> --squash --delete-branch
openspec archive <change-name> --yes
```

Project item moves to Done only after merge and archive.
