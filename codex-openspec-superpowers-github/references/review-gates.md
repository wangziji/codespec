# Review Gates

Use these gates exactly in order. Do not proceed past a gate while it has unresolved actionable findings.

## Proposal and Specs Review

Check:

- User request or GitHub issue acceptance criteria are represented.
- Scope is specific enough to implement in one branch.
- Specs describe observable behavior, not implementation wishes.
- Scenarios cover success, failure, permissions, edge cases, and compatibility.
- Risks and out-of-scope items are explicit.
- No placeholder text, contradictions, or ambiguous terms remain.

Repair:

- Fix artifacts directly.
- If a finding changes scope, update proposal and specs together.
- Re-review the touched sections before moving to design.

## Design Review

Check:

- Design follows existing repo patterns and module boundaries.
- Data flow, interfaces, storage, jobs, migrations, and external calls are clear.
- Error handling and security/privacy behavior are explicit.
- Rollout, backward compatibility, and observability are addressed when relevant.
- Test strategy proves every requirement and important scenario.
- Alternatives are real and the selected approach is justified.

Repair:

- Fix design directly.
- If design changes expected behavior, update proposal/specs and re-run their review gate.

## Tasks Review

Check:

- Tasks are ordered by dependency and can be executed without re-planning.
- Each code task names the failing test or verification to create first.
- Tasks trace back to specs and design sections.
- Review, artifact sync, and PR preparation are included.
- No task says only "implement", "wire up", "clean up", or similarly vague wording.

Repair:

- Split large tasks.
- Add missing RED/GREEN verification details.
- Add explicit artifact-update tasks for any expected drift.

## Code Review Gate

Check:

- Tests and verification commands pass or failures are explained.
- Code implements specs and design without unrelated refactors.
- Edge cases, error handling, concurrency, permissions, and migrations are covered.
- OpenSpec tasks are checked only when evidence exists.
- Artifacts match the final implementation.

Repair:

- Fix findings.
- Rerun affected checks.
- Update OpenSpec artifacts and PR body with final evidence.
