# Workflow

`spec-workflow` 是全局 OpenSpec/Superpowers gate runtime。它不替代 GitHub Project、Issue、PR、Release、Archive 等上层交付 Skill，只提供跨 repo 复用的确定性约束。

## 生命周期

Codex 默认通过自动编排循环推进：

```bash
python3 ~/.agents/skills/spec-workflow/scripts/osdd.py autopilot <change>
```

循环规则：

1. Codex 运行 `autopilot`，读取 `stage`、`assistant_actions`、`human_actions`。
2. Codex 自己执行所有 `assistant_actions`，包括 `/opsx:*`、Superpowers、CodeGraph/LSP、subagent、TDD、review 和 gate。
3. Codex 每完成一个阶段后重新运行 `autopilot`，直到 `ready: true` 或遇到真实阻塞。
4. 只有 `human_actions` 需要询问用户；不要让用户手动调用 CLI、Superpowers 或 subagent。

阶段事实：

- `planning`：需求不清楚时 Codex 先用 `/opsx:explore`，再用 `/opsx:propose <change>` 创建 OpenSpec change；通过 `superpowers:brainstorming` 产出 `proposal.md` 和 `design.md`，通过 `superpowers:writing-plans` 产出 `tasks.md`，并写入真实 audit evidence。
- `before-apply`：Codex 使用 CodeGraph/LSP 和 `superpowers:subagent-driven-development` 准备实施编排；UI change 等待人工设计批准；通过后才允许实施。
- `implementation`：Codex 使用 `/opsx:apply <change>`，按 subagent 编排和 `superpowers:test-driven-development` 实施，运行测试、lint、typecheck、视觉验证，并做 `code-review-and-quality`。
- `ready`：Codex 运行 `gate --phase ci`、`/opsx:verify <change>`、`/opsx:sync`，完成合并/发布后再 `/opsx:archive <change>`。

如果当前运行时不支持 `/opsx:*` 或必需技能，Codex 停止并报告能力缺失。不要手写文件冒充命令、技能或审批已发生。

## OpenSpec 结构

保持 OpenSpec 原生目录：

```text
openspec/
├── specs/
└── changes/
    └── <change-name>/
        ├── proposal.md
        ├── design.md
        ├── tasks.md
        ├── specs/
        └── artifacts/
            ├── prototype.html
            ├── penpot.md
            ├── design-review.md
            ├── code-review.md
            ├── validation.md
            ├── workflow-commands.md
            ├── retrieval.md
            ├── screenshots/
            └── superpowers/
```

不要创建并行状态机，例如 `specs/proposals/`、`specs/approved/`、`designs/`、`tasks/doing/`。
