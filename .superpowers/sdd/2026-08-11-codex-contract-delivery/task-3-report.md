# Task 3 report — Contract Graph and Approval Invalidation

## Delivered requirements

| Requirement | Evidence |
| --- | --- |
| One baseline plus one delivery delta, with baseline race protection | `ContractGraph.resolve`; `test_graph_rejects_delivery_based_on_different_baseline` |
| Origin for every effective node and generated-only trace output | `EffectiveContract.origins`, `trace`; origin and trace tests |
| No last-write-wins, no child deletion/weakening | `CDD-GRAPH-CONFLICT`, `CDD-GRAPH-CHILD-WEAKENING` tests |
| Generated files never become inputs | baseline scan exclusion and `CDD-GRAPH-GENERATED-INPUT` test |
| Dependency-bound approval invalidation | immutable `ApprovalRecord`, `ApprovalVerifier`, stale-dependency tests |
| Conservative L0/L1/L2 classification | `classify_change`; unknown kind is L2 test |

## TDD evidence

- RED 1: focused collection failed with `ModuleNotFoundError` for both required modules.
- GREEN 1: graph and approval tests passed after minimal public implementations.
- RED 2: child deletion returned the wrong code and trace was empty after temporary branch removal; restoring the branches made both pass.
- RED 3: an owner reference into `.codex-delivery/generated/` resolved before the guard; the new guard made the test pass.

## Validation

- Focused Task 3: `11 passed`.
- Task 1/2 regression (`test_cli.py`, `test_canonical.py`): `42 passed`.
- Full suite: `53 passed`.
- Ruff: passed. `git diff --check`: passed.

## CodeGraph and review

- CodeGraph status reported only six indexed files and did not include the package; no sync tool was available. Used a narrow `rg --files` plus direct reads of the Task 1/2 public modules, schemas, templates, and tests as fallback.
- Negative coverage includes duplicate delta conflicts, baseline races, generated inputs, child deletion, stale dependencies, and unknown change kinds.
- Self-review: immutable dataclasses/mapping proxies protect returned models; no Task 4 state machine, SQLite, or CLI wiring was added. Risk: v1 only parses `PRODUCT.md` owner records because the existing v1 schemas do not define generic product-record schemas.

## Commit

`feat(workflow): resolve contracts and approvals`
