# Design Review

`artifacts/design-review.md` 是人工设计评审门禁。

Codex 可以：

- 生成 review 草稿。
- 提出 `changes-requested` 建议。
- 补充 checklist 和 review notes。

Codex 不可以：

- 把状态改为 `approved`。
- 代替人类确认可实施。
- 在未 approved 时继续 implementation。

允许状态：

```yaml
status: pending
status: changes-requested
status: approved
```

只有 `approved` 才允许 `before-apply` gate 通过。默认模板必须是 `pending`。
