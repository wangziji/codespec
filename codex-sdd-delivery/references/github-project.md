# GitHub Project First

GitHub Project is the source of truth for what Codex should work on next.

## Required Discovery

Run these commands before selecting work:

```bash
gh auth status
gh project item-list <project-number> --owner <owner> --format json
gh project field-list <project-number> --owner <owner> --format json
```

If `gh auth status` does not show `project` scope, run:

```bash
gh auth refresh -s project
```

## Item Selection Rules

Select work in this order:

1. Highest priority unblocked item.
2. Item whose dependencies are already Done or not required.
3. Item with a linked issue or enough body detail to create one.
4. Item whose scope fits one short-lived branch and PR.

Do not pick a random issue when a Project item is available.

## Required Item Links

Each active Project item must track:

- GitHub issue URL.
- Branch name.
- OpenSpec change path.
- PR URL after PR creation.
- Current gate.
- Latest validation evidence.
- Latest review evidence.

## Project Updates

Update the Project item at these transitions:

- selected -> `Specifying`
- proposal review approved -> `Spec Review`
- all spec reviews approved -> `Designing`
- design review approved -> `Tasking`
- tasks review and OpenSpec validation approved -> `Implementing`
- PR opened -> `Code Review`
- CI and review approved -> `Ready to Merge`
- PR merged and OpenSpec archived -> `Done`
- any blocking ambiguity or failed gate -> `Blocked`

Use field discovery before edits. Do not hard-code field IDs unless the project handbook already provides stable IDs.

## Command Patterns

List items:

```bash
gh project item-list <project-number> --owner <owner> --format json
```

List fields:

```bash
gh project field-list <project-number> --owner <owner> --format json
```

Edit an item:

```bash
gh project item-edit --project-id <project-id> --id <item-id> --field-id <field-id> --single-select-option-id <option-id>
```

Create a draft item when no issue exists yet:

```bash
gh project item-create <project-number> --owner <owner> --title "<title>" --body "<body>" --format json
```

## Drift Rules

- Project item cannot be `Done` unless PR is merged and OpenSpec archive is complete.
- Project item cannot be `Implementing` unless tasks review and OpenSpec strict validation passed.
- Project item cannot be `Designing` unless every spec review is approved.
- Project item cannot be `Code Review` unless a PR exists and links the OpenSpec change.
