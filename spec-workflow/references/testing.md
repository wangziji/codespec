# Testing

生成或修改 Skill 后运行：

```bash
python3 /Users/mark/.skills/.system/skill-creator/scripts/quick_validate.py ~/.agents/skills/spec-workflow
python3 -m py_compile ~/.agents/skills/spec-workflow/scripts/osdd.py
python3 ~/.agents/skills/spec-workflow/scripts/osdd.py --help
python3 ~/.agents/skills/spec-workflow/scripts/osdd.py selftest
python3 ~/.agents/skills/spec-workflow/scripts/osdd.py doctor --json
```

如果 `quick_validate.py` 因系统 Python 缺少 `PyYAML` 失败，不要修改系统 Python；使用临时 virtualenv 安装 `PyYAML` 后再运行。

## Fixture test

在安全测试目录运行：

```bash
python3 ~/.agents/skills/spec-workflow/scripts/osdd.py new sample-change --ui --fullstack --json
python3 ~/.agents/skills/spec-workflow/scripts/osdd.py status sample-change --json
python3 ~/.agents/skills/spec-workflow/scripts/osdd.py gate sample-change --phase planning --json
```

## 手动行为检查

- 缺少 Superpowers artifact 时，planning gate 失败。
- 只有 marker 和空 Superpowers audit 文件时，planning gate 失败。
- Superpowers audit 缺少 `spec_workflow_audit: v1`、正确 `skill`、正确 `target` 或原始交互证据时，planning/before-apply/after-apply gate 失败。
- `workflow-commands.md` 缺少 `/opsx:propose`、planning gate、before-apply gate 或 `/opsx:apply` 对应阶段证据时 gate 失败。
- `retrieval.md` 缺少 CodeGraph/LSP entrypoints 和 scope decisions 时 before-apply/after-apply gate 失败。
- `code-review.md` 不是 `code-review-and-quality` workflow evidence 时 after-apply/CI gate 失败。
- `design-review.md` 不是 `approved` 时，before-apply gate 失败。
- 生产代码改变但缺少 `tdd-log.md` 时，CI gate 失败。
- `ui-level major` 但 Penpot 是 `not-applicable` 且无人工说明时，before-apply gate 失败。
- `ui-level minor` 且 Penpot 是 `not-applicable` 时，缺少 reason 会失败。
- 有 blocking code review finding 时，after-apply gate 失败。

## 压力场景

这些场景用于验证纪律型 Skill 是否能抵抗常见绕过理由。每次修改 `SKILL.md`、gate 规则或模板后，至少跑 `selftest` 并手动抽查一项。

| 压力 | 预期 gate 行为 |
| --- | --- |
| “只是小改，先写代码再补 OpenSpec” | CI gate 对生产代码无 change 失败 |
| “Superpowers 太重，marker 先手写一下” | planning gate 要求 marker 和结构化 workflow evidence 同时存在 |
| “先补 audit 文件骗过 gate” | audit schema 缺少真实流程字段和 transcript 时失败 |
| “命令我跑过了，不记录也可以” | `workflow-commands.md` 缺失对应命令证据时失败 |
| “我查过代码，不用记录入口” | `retrieval.md` 缺少 CodeGraph/LSP evidence 时失败 |
| “我自己看了一眼代码，算 review” | `code-review.md` 必须声明 `code-review-and-quality` workflow evidence |
| “设计很明显，不需要人审” | before-apply gate 要求 `design-review.md` 人工 `approved` |
| “UI 小改，Penpot 不适用但不解释” | before-apply gate 要求 not-applicable reason |
| “测试晚点补，先合 PR” | after-apply/CI gate 要求 TDD log 和 validation evidence |
| “Review 有 blocking finding 但不影响这次” | after-apply/CI gate 对 blocking finding 失败 |

## 常见借口

| 借口 | 事实 |
| --- | --- |
| “我知道当前状态，不用跑 CLI” | 状态必须由 `osdd.py status` 和 `osdd.py gate` 判断。 |
| “这是文档约束，CI 不用管” | 能转成文件、状态、marker 或命令输出的规则必须进 gate。 |
| “文件齐了就说明流程走过了” | 文件只是证据载体；缺真实 Superpowers 交互证据就是违规。 |
| “人审我可以代填 approved” | Codex 不能 approve 自己的 design review。 |
| “测试后补也一样” | TDD log 必须证明先失败再实现再通过。 |

## Review checklist

- `description` 只描述触发场景，不偷跑完整流程。
- 强约束都能转成文件、状态、marker 或命令输出。
- CLI 有明确 exit code 和 JSON 输出。
- CI 有 vendored fallback。
- `SKILL.md` 保持短，references 一层链接。
