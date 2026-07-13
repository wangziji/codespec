# CodeGraph / LSP

实施前必须先用 CodeGraph 或 LSP 定位相关范围。不要一开始全仓库扫描，不要无范围地 grep，不要先读大量无关文件。

优先检索：

- find symbols
- find references
- find callers
- find tests
- find API entrypoints

最终回复必须说明使用了哪些检索入口，例如：

- CodeGraph symbols
- LSP references
- direct tests
- API entrypoints

同时必须写入：

```text
openspec/changes/<change>/artifacts/retrieval.md
```

该文件必须包含 `spec_workflow_evidence: v1`、`kind: codegraph-lsp`、`status: completed`、原始交互证据、CodeGraph/LSP entrypoints、找到的 symbols/references/tests，以及 scope decisions。只在最终回复里口头说明不够。

## Gate 行为

`doctor` 和 `before-apply` 会检查 CodeGraph 和项目类型对应 LSP。

项目类型根据文件判断：

- `package.json`: Node / Frontend
- `go.mod`: Go
- `pom.xml`: Maven Java
- `build.gradle`: Gradle Java/Kotlin
- `pyproject.toml`: Python
- `requirements.txt`: Python

如果项目确实没有可用 LSP，必须在 `artifacts/validation.md` 写入明确 `LSP skip reason`。
