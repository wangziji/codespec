# UI Design

UI 设计沉淀在同一个 OpenSpec change 中：

```text
design.md
artifacts/prototype.html
artifacts/penpot.md
artifacts/design-review.md
```

## UI level

- `none`: 非 UI change。CLI 不强制 Penpot、prototype 或 design review。
- `minor`: 小型 UI 文案、样式、低风险状态修复。允许 `penpot.md` 为 `not-applicable`，但必须在 `tasks.md` 写明原因。
- `major`: 新页面、新流程、复杂交互、视觉设计或跨端响应式变化。必须有 prototype、Penpot handoff、design review。

`new <change> --ui` 等价于 `--ui-level major`。

## Design content

`design.md` 对 major UI 必须包含 `UI / UX Design`，并覆盖：

- 用户流程
- 页面结构
- 组件
- 状态
- 异常
- 响应式
- 埋点
- 可访问性

## Prototype

`artifacts/prototype.html` 必须是可直接打开的 HTML/Tailwind 风格原型，不依赖 build step。它需要展示 loading、empty、error、success 等状态。

## Validation

UI implementation 完成后，`artifacts/validation.md`、`artifacts/screenshots/` 或 `tdd-log.md` 必须包含截图或视觉验收说明。
