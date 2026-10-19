# 文档索引

当前文档形成对象存储湖方向的产品/技术架构 v0.3；复审后按可验收切片实施。用户已确定的边界、研究推荐基线和实测支持能力分别标记；任何能力在实现和验证前都不能被标为已支持。

| 文档 | 内容 |
| --- | --- |
| [用户手册](user/README.md) | 对客功能、架构、安装部署、使用、运维、开发、诊断及验证范围 |
| [最新实现与测试复审](reviews/2026-10-18-implementation-and-tests.md) | 主线PG入口、模块/客户端状态对账、双接口场景与严格覆盖率缺口 |
| [2026-10-18 功能与架构复审](reviews/2026-10-18-capability-architecture.md) | 当前主线证据、12个功能域完成度、执行/生命周期/多机风险 |
| [A0 集成复核](reviews/2026-10-18-a0-integration.md) | 能力合同、M0证据保全、独立真值与窗口负载；完成边界及后续准入条件 |
| [源码能力清单 v1](../api/capabilities/v1.json) | 12个功能域的机器可读离线合同；不代表在线部署协商 |
| [A0 synthetic P0 负载合同](design/a0-workload-contract.md) | 固定源输入、独立算法真值、8次窗口更新、预算与未测成本 |
| [下一阶段行动计划](plans/2026-10-18-next-stage.md) | 样本选择、读取扩展性、历史保留、质量收口与跨机 POC 的依赖和验收 |
| [产品定位](vision.md) | AI 训练、推理、应用的目标场景与产品边界 |
| [产品技术调研](research/README.md) | 官方证据、竞品与技术方案比较、选择与风险 |
| [产品功能架构](product/functional-architecture.md) | 12 个能力域、优先级、核心对象与用户流程 |
| [湖同步与服务化目标](product/lake-sync-and-serving.md) | 湖加工结果接入、刷新模式、写入权威、同步进度与索引共同发布 |
| [记录身份与版本合同](product/data-contracts.md) | 稳定键/无键源、记录版本、查询视图、对象保留与访问边界 |
| [总体架构 v0.3](architecture.md) | 分阶段接入的验证栈、湖与物化层、发布、一致性与分布式 |
| [格式兼容矩阵](compatibility/lake-formats.md) | 表格式、文件格式、训练数据集、兼容级别与验证 |
| [查询和客户端](interfaces/query-and-clients.md) | PostgreSQL、SQL、HTTP、CLI 与 MCP |
| [PG SQL 端口与 SDK](design/pg-wire-running.md) | 本机 PG wire 切片、psql/Psycopg 配置、支持与拒绝范围及验证状态 |
| [路线图](roadmap.md) | 阶段目标、依赖与验收条件 |
| [决策清单与 ADR](decisions/README.md) | 已确定方向、待决问题与记录模板 |
| [模块地图](../modules/README.md) | 代码落位与责任边界 |
| [HTTP 契约](../api/http/README.md) | 机器可读草案及其当前限制 |
| [示例说明](../examples/README.md) | 可讨论的 SQL 数据模型和请求样例 |
| [测试规划](../tests/README.md) | 现有单元/双接口场景、严格覆盖率与兼容性/故障/性能缺口 |
| [Agent Harness](../harness/README.md) | 工作闭环、模块约束、变更门禁、性能/故障证据与 CI |
| [Git 追溯与恢复](../harness/version-control.md) | 起始/最终 commit、检查点、提交前门禁与安全回滚 |
| [开发流程](../harness/development-workflow.md) | 任务起止、验收/复核、失败与交接、证据归档 |
| [GitHub Actions CI/CD](../harness/ci-cd.md) | 当前 CI 配置、远端接入与后续 CD 合同 |
| [本次设计复审](reviews/2026-10-17-implementation-readiness.md) | 实施阻碍、修正位置、门禁前后范围与验证边界 |

M0/M1、部分M2、本地worker与离线恢复的实际范围按上述复审及下方实施文档核对；下一步先补齐用户数据准备和扩展性基础。各组件按独立白名单验收，完整M2/M3/M4尚未完成；实施范围统一以路线图为准。

文档状态采用：`需求基线`、`提案`、`推荐基线（待 POC）`、`已接受`、`已实现并验证`、`已替代`。ADR 的接受只代表设计决定，不能单独证明功能已经实现。

M0 实施：[详细设计](design/m0-parquet-http.md)、[运行说明](design/m0-running.md)、[验收映射](design/m0-validation.md)、[任务计划](plans/m0-parquet-http.md)。

PG wire 独立切片：[设计决定](decisions/0014-bounded-pg-wire.md)、[配置与客户端](design/pg-wire-running.md)、[变更计划与证据](design/pg-wire-change-plan.md)。它扩展 M0 的接入协议，不改变 M1/M2 控制面或检索作业范围。

M1 实施：[详细设计](design/m1-snapshot-serving.md)、[运行说明](design/m1-running.md)、[验收映射](design/m1-validation.md)、[任务计划](plans/2026-10-17-m1-foundations.md)。

- [M2 与本地三 worker 操作](design/m2-running.md)
