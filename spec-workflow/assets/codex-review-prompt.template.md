# Codex Review Prompt

请审查这个 PR 是否符合 `spec-workflow`。不要批准 PR。只输出 review comments 和 blocking issues。

检查：

- PR 关联了 `openspec/changes/<change>/` 下的 OpenSpec change。
- `proposal.md`、`design.md`、`tasks.md` 与 delta specs 一致。
- `proposal.md` 和 `design.md` 由 `superpowers:brainstorming` 产出，并包含必需 marker。
- `tasks.md` 由 `superpowers:writing-plans` 产出，并包含必需 marker。
- UI changes 包含 `artifacts/prototype.html`、`artifacts/penpot.md` 和 `artifacts/design-review.md`。
- `design-review.md` 在 implementation 前已由人类 approved。
- Implementation 包含 `artifacts/superpowers/subagent-implementation.md`。
- 行为变更 implementation 包含 `artifacts/superpowers/tdd-log.md`。
- Implementation evidence 写明 CodeGraph/LSP retrieval entrypoints。
- PR 包含 `artifacts/code-review.md`，且没有未解决的 blocking findings。
- CI gate 是 blocking 且已经通过。
