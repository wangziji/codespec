# Project Status Map

Use these statuses when the target GitHub Project supports them. If the Project has different names, map the nearest equivalent and record the mapping in the Project item or issue.

| Status | Meaning | Allowed Next Status |
| --- | --- | --- |
| Backlog | Not ready for Codex work | Ready, Blocked |
| Ready | Prioritized and eligible for intake | Specifying, Blocked |
| Specifying | Proposal is being created or reviewed | Spec Review, Blocked |
| Spec Review | Capability specs and independent reviews are in progress | Designing, Blocked |
| Designing | Technical design is being created or reviewed | Tasking, Blocked |
| Tasking | Tasks are being created, reviewed, and validated | Implementing, Blocked |
| Implementing | TDD implementation is in progress | Code Review, Blocked |
| Code Review | PR, CI, and code review are active | Ready to Merge, Implementing, Blocked |
| Ready to Merge | Required review and CI passed | Done, Blocked |
| Done | PR merged and OpenSpec archived | Backlog only for reopened work |
| Blocked | Cannot proceed without resolution | Previous non-blocked status after blocker clears |

## Required Evidence by Status

| Status | Evidence |
| --- | --- |
| Specifying | Linked issue, branch, OpenSpec change path |
| Spec Review | Proposal review approved |
| Designing | Every `reviews/specs/*.review.md` says `Decision: Approved` |
| Tasking | Design review approved |
| Implementing | Tasks review approved and OpenSpec strict validation passed |
| Code Review | PR URL and local verification evidence |
| Ready to Merge | CI, code review, and OpenSpec validation passed |
| Done | Merge commit or merged PR URL and OpenSpec archive confirmation |
