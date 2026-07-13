---
spec_workflow_evidence: v1
kind: openspec-cli
target: workflow-commands
status: pending
transcript_captured: true
created_at: ""
---

# Workflow Commands Evidence

## Required command invocation

按实际运行顺序记录 `/opsx:*` 和 `osdd.py` 命令。此文件证明 command flow，但不能替代命令本身。

## Raw command transcript

```text
$ /opsx:propose <change>
$ python3 ~/.agents/skills/spec-workflow/scripts/osdd.py gate <change> --phase planning
$ python3 ~/.agents/skills/spec-workflow/scripts/osdd.py gate <change> --phase before-apply
$ /opsx:apply <change>
```

## Commands run

## Results

## Notes
