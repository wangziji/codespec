# Penpot

Penpot 是 UI 设计衔接，不替代 OpenSpec。推荐路径：

```text
artifacts/prototype.html -> Penpot import / linked design -> artifacts/penpot.md -> design review approved
```

`artifacts/penpot.md` frontmatter 支持：

```yaml
status: linked
status: import-ready
status: not-applicable
```

规则：

- `ui-level major` 默认不允许 `not-applicable`。
- `ui-level minor` 允许 `not-applicable`，但必须在 `tasks.md` 写明原因。
- `before-apply` 阶段 major UI 要求 `linked` 或 `import-ready`。
- `linked` 最好填写 `penpot_url`。
- `import-ready` 必须保留 `source_artifact: "prototype.html"`。

设计 review 通过后才能实施。
