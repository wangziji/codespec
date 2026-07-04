# PR Template

Use this as the body for SDD delivery pull requests.

```markdown
## Source

- Project item: <project item URL or ID>
- Issue: <issue URL>
- Branch: <branch name>
- OpenSpec change: `openspec/changes/<change-name>/`

## Gate Evidence

- Proposal skill gate: `superpowers:brainstorming`
- Proposal review: Approved
- Spec skill gate: `superpowers:brainstorming`
- Spec reviews:
  - `<capability>`: Approved in `openspec/changes/<change-name>/reviews/specs/<capability>.review.md`
- Design skill gate: `superpowers:brainstorming`
- Design review: Approved
- Tasks skill gate: `superpowers:writing-plans`
- Tasks review: Approved
- Implementation skill gate: `superpowers:subagent-driven-development`
- Code review skill gate: `code-review-and-quality`
- Documentation language gate: Chinese for proposal, specs, design, tasks, review artifacts, and PR evidence, except for literal identifiers or commands that must remain unchanged
- OpenSpec validation: `openspec validate <change-name> --type change --strict --no-interactive`
- CodeGraph status: `codegraph status .`

## Implementation Summary

- <change summary bullet>

## Verification

- <test command and result>
- <build/lint command and result>
- <CodeGraph query/impact/affected command and result for code-changing work>
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
