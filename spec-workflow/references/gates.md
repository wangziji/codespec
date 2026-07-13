# Gates

所有 gate 都通过 `scripts/osdd.py` 执行。不要靠 Codex 自己判断阶段状态。

默认入口是：

```bash
python3 ~/.agents/skills/spec-workflow/scripts/osdd.py autopilot <change>
```

`autopilot` 负责自动初始化、创建 scaffold、判断阶段、返回 Codex 应执行的 `assistant_actions`。下面的 `gate` 命令是 Codex 在执行 `assistant_actions` 时使用的阶段校验，不是要求用户手动调用的步骤。

## Planning gate

命令：

```bash
python3 ~/.agents/skills/spec-workflow/scripts/osdd.py gate <change> --phase planning
```

检查：

- `proposal.md`、`design.md`、`tasks.md` 存在。
- `specs/` 下至少存在一个 delta spec。
- `proposal.md` 包含 `Goals`、`Non-goals`、`Impact`、`Open Questions`。
- `design.md` 包含 `Technical Design` 或等价章节。
- `tasks.md` 包含 checklist。
- Superpowers audit artifacts 存在。
- Superpowers audit artifacts 必须包含 `spec_workflow_audit: v1`、正确 `skill`、正确 `target`、`status: completed`、`transcript_captured: true` 和 `Raw interaction transcript`。
- `artifacts/workflow-commands.md` 必须包含 `spec_workflow_evidence: v1`、`kind: openspec-cli`、`status: completed`，并记录 `/opsx:propose`。
- `proposal.md`、`design.md`、`tasks.md` 包含 required marker。
- `ui-level major` 包含 `UI / UX Design`、prototype、Penpot、design review。

## Before-apply gate

命令：

```bash
python3 ~/.agents/skills/spec-workflow/scripts/osdd.py gate <change> --phase before-apply
```

除 planning gate 外，还检查：

- `artifacts/superpowers/subagent-implementation.md` 存在。
- `subagent-implementation.md` 必须通过 Superpowers audit schema。
- `workflow-commands.md` 必须记录 planning gate 命令结果。
- `artifacts/retrieval.md` 必须包含 `kind: codegraph-lsp`、`status: completed`、CodeGraph/LSP entrypoints、scope decisions 和 raw transcript。
- `superpowers:subagent-driven-development` 和 `superpowers:test-driven-development` 可用。
- CodeGraph 可用。
- 项目类型对应 LSP 可用，或 `artifacts/validation.md` 写明 `LSP skip reason`。
- UI change 的 `design-review.md` 必须是人工 `approved`。
- `ui-level major` 的 `penpot.md` 状态必须是 `linked` 或 `import-ready`。
- `ui-level minor` 如果 `penpot.md` 状态是 `not-applicable`，必须在 `tasks.md` 或 `penpot.md` 写明原因。

失败时 Codex 必须停止实施。

## After-apply gate

命令：

```bash
python3 ~/.agents/skills/spec-workflow/scripts/osdd.py gate <change> --phase after-apply
```

检查：

- `tasks.md` implementation checklist 完成。
- 测试、lint、typecheck 有证据。
- `subagent-implementation.md` 存在。
- `tdd-log.md` 存在，并包含 `Failing test`、`Implementation`、`Passing test`、`Validation commands`。
- `tdd-log.md` 必须通过 Superpowers audit schema，不能只是事后补的普通日志。
- UI change 有截图或视觉验收证据。
- `code-review.md` 存在，且 `blocking_findings: 0`。
- `code-review.md` 必须包含 `spec_workflow_evidence: v1`、`kind: skill-invocation`、`skill: code-review-and-quality`、`status: completed` 和 raw transcript。
- `workflow-commands.md` 必须记录 `/opsx:apply` 和 before-apply gate。

## CI gate

命令：

```bash
python3 ~/.agents/skills/spec-workflow/scripts/osdd.py gate --changed --phase ci
```

CI gate 根据 `git diff` 找 changed files：

- 改了业务代码但没有对应 `openspec/changes/<change>/`，失败。
- 改了 UI 文件但没有 OpenSpec change，失败。
- 改了 proposal/design/tasks 但缺少 Superpowers marker，失败。
- 改了生产代码但缺少 TDD log，失败。
- PR 前缺少 code review artifact，失败。
- `after-apply` 不干净时，CI gate 失败。
- command/retrieval/code-review evidence 缺失或只是 pending 模板时，CI gate 失败。

`assets/github-workflow.template.yml` 是 blocking gate 模板；`init` 会把 vendored CLI 写入 `.github/spec-workflow/osdd.py`。
