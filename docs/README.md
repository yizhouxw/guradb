# 文档索引

当前概要设计v0.6以业务场景与官方竞品证据细化完整AI多模态数据库的架构和并行实施边界；用户手册按概念、任务、参考与管理员职责组织。产品目标、推荐基线和当前alpha白名单分别标记；本轮设计不新增运行时支持。

| 文档 | 内容 |
| --- | --- |
| [用户手册](user/README.md) | 概念、建模、接入、检索、训练、安全、部署与参考；区分目标与当前操作 |
| [概要设计v0.6](design/outline-design.md) | 业务场景分析、业务/技术/模块/功能/部署架构、关键技术和质量设计完整入口 |
| [本轮官方证据矩阵](research/2026-10-20-outline-design-evidence.md) | 场景、竞品/edition事实、设计推论、目标与反证验证 |
| [模块接口与责任合同](design/outline-module-contracts.md) | 唯一所有者、单向DAG、公共端口、错误/取消/预算、隔离开发与真实集成 |
| [部署与运行治理设计](design/outline-runtime-and-operations.md) | 性能、可观测性、多云认证、安全与合规控制、故障与恢复验收 |
| [并行实施计划](plans/2026-10-20-parallel-delivery.md) | 工作包、前置合同、依赖、有限并发波次、估算、集成门槛与旧任务映射 |
| [产品技术评审落实](reviews/2026-10-20-product-review-followup.md) | v0.6改动映射、内容复核、门禁与待实现边界 |
| [训练样本与消费合同](product/training-contract.md) | 样本/成员/处理版本、分组划分、采样/尾批、复现等级、真实框架验收 |
| [概要设计v0.5历史复审](reviews/2026-10-20-outline-design.md) | 文档范围、内容独立审查、验证和未实现边界 |
| [2026-10-19方向复审](reviews/2026-10-19-product-direction.md) | 用户指正、独立源码审计、产品/架构/文档偏移及已修正内容 |
| [已发布数据库与手册调研](research/2026-10-19-database-products.md) | 八个产品官方来源、架构/edition边界、手册规模和代表页深度 |
| [产品交付合同](product/product-contract.md) | 用户角色、对象关系、J1–J6完整旅程及产品完成标准 |
| [此前产品交付](plans/2026-10-19-product-delivery.md) | 产品成果/验收义务保留；任务顺序已由2026-10-20并行计划替代 |
| [手册建设合同](user/manual-plan.md) | 完整信息架构、逐域实质缺口及可执行教程/参考的验收 |
| [最新实现与测试复审](reviews/2026-10-18-implementation-and-tests.md) | 主线PG入口、模块/客户端状态对账、双接口场景与严格覆盖率缺口 |
| [2026-10-18 功能与架构复审](reviews/2026-10-18-capability-architecture.md) | 当前主线证据、12个功能域完成度、执行/生命周期/多机风险 |
| [A0 集成复核](reviews/2026-10-18-a0-integration.md) | 能力合同、M0证据保全、独立真值与窗口负载；完成边界及后续准入条件 |
| [源码能力清单 v1](../api/capabilities/v1.json) | 12个功能域的机器可读离线合同；不代表在线部署协商 |
| [A0 synthetic P0 负载合同](design/a0-workload-contract.md) | 固定源输入、独立算法真值、8次窗口更新、预算与未测成本 |
| [原A1–A6工程合同](plans/2026-10-18-next-stage.md) | 技术真值/预算/故障要求保留；执行优先级已被产品计划替代 |
| [产品定位](vision.md) | AI 训练、推理、应用的目标场景与产品边界 |
| [产品技术调研](research/README.md) | 官方证据、竞品与技术方案比较、选择与风险 |
| [产品功能架构](product/functional-architecture.md) | 12 个能力域、优先级、核心对象与用户流程 |
| [湖同步与服务化目标](product/lake-sync-and-serving.md) | 湖加工结果接入、刷新模式、写入权威、同步进度与索引共同发布 |
| [记录身份与版本合同](product/data-contracts.md) | 稳定键/无键源、记录版本、查询视图、对象保留与访问边界 |
| [技术架构 v0.6参考](architecture.md) | 共同目录/授权/查询上下文、对象模型、湖与物化层、迁移与分布式 |
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

M0/M1、部分M2、本地worker与离线恢复按历史复审和实施文档核对；下一步以产品对象、共同目录/查询和贯通旅程为主线，兼顾数据准备、规模和生命周期。完整M2/M3/M4尚未完成；阶段范围统一以路线图为准。

文档状态采用：`需求基线`、`提案`、`推荐基线（待 POC）`、`已接受`、`已实现并验证`、`已替代`。ADR 的接受只代表设计决定，不能单独证明功能已经实现。

M0 实施：[详细设计](design/m0-parquet-http.md)、[运行说明](design/m0-running.md)、[验收映射](design/m0-validation.md)、[任务计划](plans/m0-parquet-http.md)。

PG wire 独立切片：[设计决定](decisions/0014-bounded-pg-wire.md)、[配置与客户端](design/pg-wire-running.md)、[变更计划与证据](design/pg-wire-change-plan.md)。它扩展 M0 的接入协议，不改变 M1/M2 控制面或检索作业范围。

M1 实施：[详细设计](design/m1-snapshot-serving.md)、[运行说明](design/m1-running.md)、[验收映射](design/m1-validation.md)、[任务计划](plans/2026-10-17-m1-foundations.md)。

- [M2 与本地三 worker 操作](design/m2-running.md)
