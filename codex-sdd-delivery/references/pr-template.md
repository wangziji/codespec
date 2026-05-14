# PR Template

Use this as the body for SDD delivery pull requests.

```markdown
## Source

- Project item: <project item URL or ID>
- Issue: <issue URL>
- Branch: <branch name>
- OpenSpec change: `openspec/changes/<change-name>/`

## Gate Evidence

- Proposal review: Approved
- Spec reviews:
  - `<capability>`: Approved in `openspec/changes/<change-name>/reviews/specs/<capability>.review.md`
- Design review: Approved
- Tasks review: Approved
- OpenSpec validation: `openspec validate <change-name> --type change --strict --no-interactive`

## Implementation Summary

- <change summary bullet>

## Verification

- <test command and result>
- <build/lint command and result>
- <manual or browser check when relevant>

## Review Response

- Code review findings addressed:
  - <finding summary and fix evidence>

## Project Update

- Status before PR: Implementing
- Status after PR open: Code Review
- Remaining status update after merge: Done after archive

## Risks and Follow-Up

- <known risk or "None">
```

When creating the PR body, replace angle-bracket fields with real values before running `gh pr create --body-file`.
