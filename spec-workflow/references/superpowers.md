# Superpowers 集成

OpenSpec 负责文件名和生命周期。

Superpowers 负责 authoring 和 implementation discipline。

## 必需映射

- `proposal.md` 必须由 `superpowers:brainstorming` 产出
- `design.md` 必须由 `superpowers:brainstorming` 产出
- `tasks.md` 必须由 `superpowers:writing-plans` 产出
- implementation orchestration 必须使用 `superpowers:subagent-driven-development`
- 行为变更 implementation 必须使用 `superpowers:test-driven-development`

## 原因

- `brainstorming` 避免浅层 proposal/design 生成。
- `writing-plans` 让 tasks 可执行且有顺序。
- `subagent-driven-development` 让 implementation slices 独立、可审查。
- `test-driven-development` 强制从测试开始，而不是从猜测性代码修改开始。

## Audit artifacts

每个 change 应包含：

```text
openspec/changes/<change>/artifacts/superpowers/
├── brainstorm-proposal.md
├── brainstorm-design.md
├── write-plan-tasks.md
├── subagent-implementation.md
└── tdd-log.md
```

这些文件不是装饰性的 checkbox。它们是必需 Superpowers workflow 真实发生过的证据。

每个 audit file 必须包含 frontmatter：

```yaml
spec_workflow_audit: v1
skill: superpowers:brainstorming
target: proposal.md
status: completed
transcript_captured: true
```

每个 artifact 使用对应的 `skill` 和 `target`。

每个 audit file 还必须包含：

- `Required skill invocation`
- `Raw interaction transcript`
- 阶段相关决策章节
- `Resulting updates` 或 `Completion evidence`

`osdd.py` 会拒绝空 audit file、placeholder text、缺少 transcript section、缺少 skill declaration、以及过短到不像真实 workflow evidence 的 audit file。

重要限制：`osdd.py` 不能读取 Codex 的隐藏推理。gate 是必要条件但不是充分条件。Codex 必须在写入目标文件前真实加载并遵循必需 Superpowers skill。事后补写看似合规的 audit file 属于 workflow violation，即使较弱的结构检查可能通过。

## Required markers

`proposal.md`:

```markdown
<!-- spec-workflow: superpowers=brainstorming -->
```

`design.md`:

```markdown
<!-- spec-workflow: superpowers=brainstorming -->
```

`tasks.md`:

```markdown
<!-- spec-workflow: superpowers=writing-plans -->
```

## 规则

Codex 不能批准自己的 design review。

Codex 不能跳过 Superpowers。

Codex 不能用 marker 和 audit files 替代运行 Superpowers。

`before-apply` gate 通过前，Codex 不能实施。

没有测试命令和结果时，Codex 不能把 TDD 标记为完成。
