# AI 大型项目开发框架版图（截至 2026-08-10）

## 结论先行

**目前不存在一个成熟框架，能够单体、原生、可审计地覆盖“需求澄清 → Penpot 交互设计 → 架构/spec → 任务拆解与多代理编码 → 测试 → 部署 → 线上回归 → bug 修复 → 成本路由 → 契约一致性 → 学习/受控进化”的全部流程。**

现有产品所谓 “end-to-end” 通常只在自身层内成立：Codex/OpenHands 覆盖编码任务，LangGraph/Microsoft Agent Framework/CrewAI 覆盖 agent 应用，Temporal/Argo/Tekton 覆盖工作流或 CI/CD，Backstage/Port 覆盖开发者门户与治理，Spec Kit/OpenSpec 覆盖规格制品。成熟解法应是**分层组合**，并让确定性 CI、契约检查、审批和回滚成为权威门禁；不应把一个自治 agent 当作全流程控制平面。

这里的“成熟度”不是供应商宣传排名，而是根据官方文档中的稳定性声明、持久化/恢复、权限治理、可观测性和明确的 preview/experimental 警告综合判断。

## 框架比较

| 框架/产品 | 成熟度判断 | 已覆盖的核心能力 | 对完整流程的关键缺口 |
|---|---|---|---|
| [OpenAI Codex](https://openai.com/index/introducing-the-codex-app/) + [GitHub](https://docs.github.com/en/copilot/concepts/agents/hooks) | **生产可用的编码与协作层**；Codex 核心已[正式 GA](https://openai.com/index/codex-now-generally-available/)，部分 Copilot agent 扩展仍有 preview 边界 | 多 agent 并行、worktree 隔离、skills、自动化、代码审查、GitHub issue/PR/CI 集成；hooks 可做确定性命令拦截和审计 | 不原生管理 Penpot 设计真相、跨系统持久流程、发布回滚、生产观测、契约注册表或组织级学习治理。Codex automations 是后台/定时任务，不等同于具备事件历史和确定性恢复的 durable workflow engine；[Copilot code review](https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/copilot-code-review) 也不会代替正式批准或 required approval |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/graph-api) + [LangSmith](https://docs.langchain.com/langsmith/evaluation) | **成熟的 agent 运行时/评测层**；LangGraph 1.0 按官方[发布策略](https://docs.langchain.com/oss/python/release-policy)为 LTS/production-ready stable API | 状态图、分支/循环、[checkpoint/persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、中断恢复、HITL、离线/在线评测、trace、反馈与[成本跟踪](https://docs.langchain.com/langsmith/cost-tracking) | 是通用 agent 应用框架，不是软件交付套件；不负责产品需求、Penpot、Git/PR 语义、任意应用部署或契约治理。成本“观测”不等于自动做出可靠的性价比路由 |
| [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) | **Python/.NET 1.0 已 GA，但能力成熟度不均**（见 Microsoft Foundry [2026-04 官方更新](https://devblogs.microsoft.com/foundry/whats-new-in-microsoft-foundry-apr-2026/)） | agents、tools、sessions/persistence、workflow、[长时任务 harness](https://learn.microsoft.com/en-us/agent-framework/agents/harness)、审批与可观测性；适合 Microsoft/Azure 生态 | [self-hosting](https://learn.microsoft.com/en-us/agent-framework/hosting/self-hosting) 中部分 Python 包为 prerelease，Go 为 public preview，应用仍需自行承担 identity、auth、routing、storage、scaling；[declarative workflows](https://learn.microsoft.com/en-us/agent-framework/workflows/declarative) 也有 prerelease 边界。不是 SDLC 控制平面 |
| [AutoGen](https://github.com/microsoft/autogen) | **维护模式，不建议新建战略底座** | 多 agent 对话、工具、实验性图编排；生态和研究积累仍有价值 | 官方 README 已建议新用户转向 Microsoft Agent Framework，并明确 AutoGen Studio 是 prototype/demo、非 production-ready；不宜承担新的长期交付平台 |
| [CrewAI](https://github.com/crewAIInc/crewai) | **活跃、生产导向；成熟度主要来自项目/厂商自述** | Crews 的角色协作；Flows 的事件驱动、状态、条件分支；企业控制面提供观测、RBAC、云/本地部署 | Python 通用 agent 框架而非 SWE/SDLC 系统；spec、设计、Git、CI/CD、部署、契约及沙箱均需另接。Visual Agent Builder 是 agent 配置，不是产品交互设计系统 |
| [OpenHands](https://github.com/OpenHands/openhands) | **活跃的编码 agent/沙箱底座**；云与企业层另有商业/许可证边界 | 软件 agent SDK、CLI/GUI/cloud、代码执行沙箱、Jira/Linear/Slack 等连接、可扩展多 agent | 适合成为“编码执行器”，不提供从产品设计到线上治理的完整生命周期；云层部署与许可需单独评估（见官方 [OpenHands Cloud](https://github.com/OpenHands/OpenHands-Cloud)） |
| [SWE-agent](https://github.com/princeton-nlp/SWE-agent/blob/main/docs/index.md) | **研究工具，原项目现为 maintenance-only，不是企业交付平台** | 以 GitHub issue 为输入，在仓库环境中定位和修复问题；ACI 研究价值高 | [官方 CLI 文档](https://swe-agent.com/latest/usage/cli/)说明原 SWE-agent 已被 mini-swe-agent 取代；缺少企业权限、持久交付编排、设计/spec、部署和治理 |
| [GitHub Spec Kit](https://github.com/github/spec-kit) | **活跃的规格工作流工具；不是运行时平台** | constitution → specify/clarify → plan → tasks → implement；`analyze` 做跨制品一致性检查，`converge` 对照代码与规格补任务，支持 30+ coding agents | 官方仍把 enterprise constraints、鲁棒迭代等列为“experimental goals”；Markdown/模板和 agent 指令不能替代可执行 API/schema 契约、CI、部署、生产回归或 durable execution |
| [OpenSpec](https://github.com/Fission-AI/OpenSpec) | **活跃、轻量、偏 brownfield 的规格制品层**；跨 repo Stores 仍为 beta | explore/propose/apply/verify/archive；proposal、requirements/scenarios、design、tasks 的 Git 化变更包；可跨多个 coding agents | 流程刻意“fluid not rigid”，因此强门禁需外加；Stores 明示 beta。它不执行 CI/CD、生产观测和跨系统恢复，也不能单靠 Markdown 防止实现/接口漂移 |
| [Temporal](https://docs.temporal.io/) | **成熟的 durable execution 组件** | 持久事件历史、故障后恢复、长时间等待、重试、补偿和跨系统审批；适合把需求批准、部署、回滚、回归等串成可恢复业务流程 | 没有 agent 推理、代码理解、spec 或设计语义；活动、权限、幂等性和版本迁移均需工程实现。不要把非确定性 LLM 直接放进要求可重放的 workflow 逻辑 |
| [Argo Workflows](https://argo-workflows.readthedocs.io/en/latest/walk-through/dag/) / [Tekton](https://tekton.dev/docs/pipelines/) | **成熟的 Kubernetes 工作流/CI-CD 组件** | DAG/fan-out/fan-in、容器任务、重试、Kubernetes 原生交付；适合测试、构建、发布、回归执行 | DAG 不天然表达开放式反馈循环；没有 agent 状态、产品需求、设计或学习治理。更适合做“确定性执行面”，而不是自治决策面 |
| [Backstage](https://backstage.io/docs/features/software-catalog/) | **成熟的 OSS 开发者门户/目录和脚手架层** | 软件目录、ownership、golden path、[Software Templates](https://backstage.io/docs/features/software-templates/) 与自定义 actions | 任务恢复/重试仍有[实验性边界](https://backstage.io/docs/features/software-templates/experimental/)；不是 durable agent 编排器、编码执行器或生产回归系统 |
| [Port](https://docs.port.io/) | **成熟的商业治理/控制平面，覆盖面最广之一** | 软件目录/context lake、scorecards、RBAC、自服务动作、agent management、审批与审计；[self-service actions](https://docs.port.io/workflows/actions-and-automations/create-self-service-experiences/) 可由人或 AI 触发 | 官方明确执行后端逻辑由客户提供并复用现有基础设施，因此它是集成/治理层而非自足单体；仍需 Codex、CI/CD、Temporal/LangGraph、部署平台等执行者，且存在商业锁定与数据治理成本 |

## Penpot、成本、契约和学习：四个容易被“已集成”误判为“已解决”的点

1. **Penpot**：上述框架没有原生提供“设计版本即交付真相”的完整门禁。Penpot 已有[官方 MCP Server](https://github.com/penpot/penpot-mcp)支持读取、变换和创建设计对象，但本地插件连接、多用户能力及权限边界需单独治理；官方文档也提示多用户模式仍在开发。应把 frame/component/token 的固定版本或 ID 写入规格与验收证据，在代码生成前、视觉回归后各设人工批准点。
2. **成本路由**：LangSmith 等能记录 token/provider/custom cost，多个 agent SDK 能切模型，但“记录”不是“路由策略”。应由显式策略控制任务分级、预算上限、超额停止、升级到强模型的条件，并用固定评测集验证；不能让 agent 自己用成功叙事证明自身成本合理。
3. **契约一致性**：Spec Kit/OpenSpec 的一致性分析主要针对文本制品。运行时仍需 OpenAPI/AsyncAPI/Protobuf、数据库迁移检查、consumer-driven contract tests、生成代码 diff、兼容性规则和集成测试成为 CI 硬门禁；否则“spec 一致”可能只是文档内部一致。
4. **学习/受控进化**：普通进化只应提出不可信的声明式 prompt、路由、检索、启发式或非权威 memory 载荷；不能把 skill、hook、工具权限或 evaluator 当成普通“数据”由线上 agent 自改发布。所有写操作应经过固定版本、最小权限并可审计的能力代理。核心缺陷另走稀有的独立维护路径。推荐链路是：生产 trace/事故 → 脱敏候选样本 → 固定回归集与独立 holdout → 人工审查版本化变更 → canary → 监控 → 可一键回滚。

## 推荐组合：以 Codex 为编码执行层，而非全局权威

### 最小可行组合

1. **需求和制品真相**：GitHub Project/Issues + Penpot + **OpenSpec 或 Spec Kit 二选一**。偏 brownfield、轻量迭代选 OpenSpec；偏治理、constitution、明确 phase/checklist/analyze 选 Spec Kit。若因历史原因并存，必须规定单向映射和唯一权威，避免两套 spec 漂移。
2. **编码和审查**：Codex 多 agent + 每任务独立 worktree/branch + GitHub PR；agent 只能提交候选变更，不能绕过 required checks、CODEOWNERS 和受保护环境批准。
3. **确定性交付**：GitHub Actions 足够时不要额外引入平台；Kubernetes 大规模流水线选择 Tekton 或 Argo。单元、集成、契约、安全、迁移、视觉和部署 smoke 均产出不可变证据。
4. **状态化 agent 质量层**：需要动态分支、循环、checkpoint、在线评测时采用 LangGraph/LangSmith；Microsoft-first 组织可用 Microsoft Agent Framework 替代。初期不要同时引入两个 agent 编排核心。
5. **跨系统长流程**：只有当存在跨天等待、人工批准、部署补偿/回滚或多系统事务时才引入 Temporal；CI 流水线仍负责具体构建和部署动作。
6. **目录与治理**：OSS 路线选 Backstage；需要商业化 agentic control plane、scorecard/RBAC/自服务治理可评估 Port。二者都不是编码引擎。

可概括为：

```text
GitHub Project + Penpot + OpenSpec/Spec Kit
                 ↓ 受批准的需求/设计/spec
       Codex + worktrees + pull requests
                 ↓ 候选代码与证据
 GitHub Actions / Tekton / Argo（硬门禁与部署）
                 ↕
 Temporal（跨系统耐久流程，可选）
 LangGraph/LangSmith 或 MAF（agent 状态、trace、eval，可选）
 Backstage 或 Port（目录、ownership、治理，可选）
```

## 主要风险和门禁

- **职责重叠和平台堆叠**：LangGraph、MAF、CrewAI 不应同时作为主编排核；Argo/Tekton/GitHub Actions 也应按现有基础设施择一主线，否则状态、重试和责任边界会分裂。
- **自治权限扩大**：skill/MCP/hook/插件会扩大 supply-chain 和命令执行面。所有外部工具需最小权限、固定版本、沙箱、出站限制和审计；高风险写操作必须 HITL。
- **奖励投机与 evaluator 过拟合**：模型可能优化评分代理而非真实目标。OpenAI 的[奖励模型过优化研究](https://openai.com/index/scaling-laws-for-reward-model-overoptimization/)和 Anthropic 的[reward tampering 研究](https://www.anthropic.com/research/reward-tampering)说明不能让同一 agent 同时定义目标、生成变更并裁决成功。
- **记忆/检索污染**：外部 issue、文档、网页和历史 trace 都应视为不可信输入；进入长期 memory 或回归集前要做来源、权限、时效、脱敏和人工审核。
- **可恢复不等于正确**：checkpoint/Temporal 能恢复执行，但也可能稳定地恢复到错误状态。每个副作用动作要有幂等键、前置条件、补偿、审计和人工逃生口。
- **供应商“production-ready/end-to-end”口径不可横比**：它通常仅表示产品自身层面。采购或落地前应做真实项目 PoC，验证并发、恢复、权限、成本、模型替换、数据驻留和降级路径。

## 最终判断与不确定性

如果目标是 Codex 大型项目交付，最稳妥的形态不是寻找“一个会自我进化的全能框架”，而是建立一条**制品可追踪、状态可恢复、门禁确定性、agent 可替换**的组合流水线。Codex 是高能力 worker/supervisor；spec、设计、CI、部署和治理分别由各自权威系统负责。

以上结论基于截至 2026-08-10 可公开访问的官方文档、原始仓库和一手研究。没有独立审计各厂商的生产承诺；不同语言 SDK、套餐、cloud/self-hosted 版本的可用性可能不同，尤其是 Microsoft Agent Framework prerelease 功能、OpenSpec Stores beta、Backstage experimental recovery、Penpot MCP 多用户模式以及 GitHub Copilot 的 preview 扩展。正式选型应按目标部署形态重新核验精确版本和许可证。
