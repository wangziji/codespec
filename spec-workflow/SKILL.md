---
name: spec-workflow
description: 当 OpenSpec change、proposal/design/tasks 修改、UI 或 Penpot 交接、CodeGraph/LSP 证据、CI gate 配置、PR review、merge/archive readiness 需要在实现或发布前做确定性校验时使用。Use when automating spec workflow, spec-driven development, OpenSpec proposal/design/tasks, UI design handoff, Penpot handoff, implementation gates, CI gates, PR review, merge readiness, or archive readiness.
---

# Spec Workflow

`spec-workflow` 是全局 OpenSpec/Superpowers gate runtime。它让 OpenSpec 负责生命周期事实，Superpowers 负责 authoring 和 implementation discipline，`osdd.py` 负责确定性门禁，Codex 负责执行，CI 负责阻止违规合并。

canonical 安装路径是 `~/.skills/spec-workflow/`。兼容 Codex 入口是 `~/.agents/skills/spec-workflow/`；在这台机器上它可以是指向 canonical 路径的 symlink。

## 默认自动编排

当用户提出需求、要求进入 OpenSpec、修改 proposal/design/tasks、做 UI 设计、实施代码、合并或归档时，Codex 必须先自动运行：

```bash
python3 ~/.agents/skills/spec-workflow/scripts/osdd.py autopilot <change>
```

`autopilot` 是 Codex 的内部编排入口，不是要求用户手动执行的命令。它会初始化 repo gate 文件、创建安全 scaffold、判断当前阶段，并返回 `assistant_actions` 与 `human_actions`：

- `assistant_actions` 必须由 Codex 自己执行，然后重新运行 `autopilot`。
- `human_actions` 才需要询问用户，例如真实 UI 设计批准、产品取舍或缺失需求。
- gate 命令仍由 Codex 在阶段内执行，用户不需要手动调用。

不要手动推断 workflow state。必须使用 `osdd.py autopilot`、`status` 和 `gate` 的输出作为阶段事实。

如果 CLI 缺失、不可运行或 gate 失败，停止并报告缺失项。不要继续实施，也不要把待办转交给用户手动跑命令。

## 按阶段读取

只读取当前阶段需要的文件：

- `references/workflow.md`：端到端生命周期
- `references/gates.md`：planning、before-apply、after-apply、CI gates
- `references/superpowers.md`：创建或修改 proposal、design、tasks、implementation 前阅读
- `references/ui-design.md`、`references/penpot.md`、`references/design-review.md`：UI change 阅读
- `references/codegraph-lsp.md`：实施前阅读
- `references/testing.md`：验证 Skill 或 CLI 前阅读

## OpenSpec 流程

Codex 在自动编排过程中使用：

- `/opsx:explore`
- `/opsx:propose <change>`
- `/opsx:apply <change>`
- `/opsx:verify <change>`
- `/opsx:sync`
- `/opsx:archive <change>`

如果当前运行时不支持 `/opsx:*`，Codex 必须报告该能力缺失并停止在对应阶段；不要手写文件冒充 `/opsx` 执行结果。

不要创建并行流程，例如 `specs/proposals/`、`specs/approved/`、`designs/` 或 `tasks/doing/`。

## Superpowers 硬依赖

此 workflow 必须依赖 Superpowers。

必需技能：

- `superpowers:brainstorming` 用于 `proposal.md`
- `superpowers:brainstorming` 用于 `design.md`
- `superpowers:writing-plans` 用于 `tasks.md`
- `superpowers:subagent-driven-development` 用于 implementation orchestration
- `superpowers:test-driven-development` 用于行为变更代码 slice
- `code-review-and-quality` 用于 merge readiness 前 review

不要直接凭模型推理编写 OpenSpec proposal、design、tasks 或 implementation。

使用 OpenSpec 文件名和结构，但内容必须通过必需技能产出。

不要把 marker 文件或 audit artifacts 当成必需流程的替代品。CLI gate 是必要条件但不是充分条件；写入目标文件前，必须真实加载并遵循对应 Superpowers skill。

如果必需技能不可用，停止并报告：

```text
Superpowers dependency missing. Required skills:
- superpowers:brainstorming
- superpowers:writing-plans
- superpowers:subagent-driven-development
- superpowers:test-driven-development
```

不要 fallback 到普通 prompt。

## 硬规则

- 不要在 OpenSpec 之外创建并行 workflow。
- `gate --phase before-apply` 通过前不要实施。
- 不要批准自己的 design review。
- major UI change 必须包含 `prototype.html`、`penpot.md` 和 `design-review.md`。
- 广泛读文件前先使用 CodeGraph/LSP。
- 在必需 evidence artifacts 中记录 `/opsx`、`osdd.py`、CodeGraph/LSP、subagent、TDD 和 code review 调用。
- Implementation 必须使用 `superpowers:subagent-driven-development` 和 `superpowers:test-driven-development`。
- 最终回复前运行 `gate --phase after-apply`。
- merge readiness 前运行 `gate --phase ci` 或 `gate --changed --phase ci`。
