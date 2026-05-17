# Spec Review Template

Each capability spec requires one independent review file.

Spec reviews may be delegated to independent reviewer agents. The reviewer agent must not author or edit the spec under review.

Spec path:

```text
openspec/changes/<change-name>/specs/<capability>/spec.md
```

Review path:

```text
openspec/changes/<change-name>/reviews/specs/<capability>.review.md
```

Do not place review files under `specs/`; OpenSpec may parse them as delta specs.

## Required Review File Content

```markdown
# Spec Review: <capability>

Decision: Changes Requested

## Source Links

- Project item: <project item URL or ID>
- Issue: <issue URL>
- Spec: `openspec/changes/<change-name>/specs/<capability>/spec.md`

## Required Findings

- [ ] Example finding format: clarify whether permission errors return `403` or `404`.

## Checks

- [ ] Covers linked GitHub issue acceptance criteria.
- [ ] Covers Project item scope.
- [ ] Requirements describe observable behavior.
- [ ] Every requirement has at least one `#### Scenario:`.
- [ ] Scenarios are testable.
- [ ] Failure and edge cases are covered.
- [ ] Security, privacy, and permission behavior are explicit when relevant.
- [ ] Compatibility, migration, removal, or rename behavior is explicit when relevant.
- [ ] No conflict with existing canonical specs.
- [ ] No ambiguous wording remains.

## Re-review Result

Decision: Approved
```

## Approval Rule

The review is approved only when:

- Required Findings is empty or every item is checked.
- Checks are complete.
- Re-review Result says `Decision: Approved`.
- The reviewer did not author or modify the reviewed spec.

Design phase is blocked until every capability spec has an approved review file.
