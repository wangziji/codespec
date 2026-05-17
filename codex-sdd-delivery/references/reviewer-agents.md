# Reviewer Agents

Use independent reviewer agents for review gates when the runtime supports sub-agents or delegated agent work. The goal is to avoid self-approval and to preserve a fresh-context review boundary.

## Independence Rules

- The authoring agent writes or fixes the artifact.
- The reviewer agent reads source inputs and the artifact, then records findings.
- The reviewer agent must not edit the artifact under review.
- The same agent must not be both author and final reviewer for the same artifact.
- If the reviewer requests changes, the authoring agent fixes them and a reviewer agent re-runs the review.
- Approval is valid only when the review artifact or review note says `Decision: Approved`.

## Reviewer Types

| Gate | Reviewer Agent | Output |
| --- | --- | --- |
| Proposal Gate | Proposal Reviewer Agent | Proposal review note or review section |
| Specs Gate | Spec Reviewer Agent per capability | `reviews/specs/<capability>.review.md` |
| Design Gate | Design Reviewer Agent | Design review note or review section |
| Tasks Gate | Tasks Reviewer Agent | Tasks review note or review section |
| Code Review Gate | Code Reviewer Agent | PR/code review findings and verification evidence |

## Required Reviewer Inputs

Every reviewer agent must receive:

- GitHub Project item URL or ID.
- GitHub issue URL.
- Current branch name.
- OpenSpec change path.
- Artifact path under review.
- Relevant upstream artifacts, such as proposal before spec review, approved specs before design review, and approved design before tasks review.
- Existing canonical specs or implementation files when compatibility matters.

## Review Decisions

Use exactly one decision:

```text
Decision: Changes Requested
Decision: Approved
```

`Decision: Changes Requested` must include concrete findings with file paths, artifact sections, or requirement/scenario names.

`Decision: Approved` means the reviewer found no blocking issues against the linked Project item, issue, upstream artifacts, and gate checklist.

## Delegation Pattern

When sub-agents are available, dispatch bounded review tasks:

```text
Review <artifact-path> against <source-inputs>. Do not edit files.
Return Decision: Approved or Decision: Changes Requested with concrete findings.
For spec review, write or update only reviews/specs/<capability>.review.md if write access is explicitly part of the task.
```

If sub-agents are not available, simulate independence by starting a fresh review pass from the source artifacts and record that the review was performed in-session.

## Stop Conditions

Stop the workflow when:

- The reviewer did not receive the Project item, issue, OpenSpec change path, or artifact path.
- The reviewer modifies the artifact under review.
- Review output lacks a decision.
- A required finding is unresolved.
- The authoring agent changes `Decision: Changes Requested` to `Decision: Approved` without a re-review.
