# 设计决策记录（ADR）

ADR 用来记录已经比较过的方案和取舍。编号只表示记录顺序；接受一项设计不能代替实现与验收。

| 编号 | 标题 | 状态 |
| --- | --- | --- |
| [0001](0001-project-scope.md) | 产品约束与初始化边界 | 已接受（来自项目初始需求） |
| [0002](0002-object-store-lake-boundary.md) | 对象存储湖与业务负载边界 | 已接受（来自本轮用户方向） |
| [0003](0003-storage-and-execution-baseline.md) | 存储与执行技术基线 | 推荐基线，待 POC |
| [0004](0004-snapshot-and-index-publication.md) | 数据版本与索引发布 | 推荐基线，待故障验证 |
| [0006](0006-lake-sync-and-serving.md) | 湖加工结果同步与服务化目标 | 产品技术目标已接受，详细协议/实现待验证 |
| [0005](0005-agent-harness-and-quality-gates.md) | Agent Harness 与质量门禁 | 工程约定已采用，harness 层已实现 |
| [0007](0007-incremental-delivery-and-gates.md) | 可验收切片与组件/发布分层门禁 | 本次设计复审采用；数据库能力待实现 |
| [0008](0008-git-traceability-and-recovery.md) | Git 追溯、检查点与安全恢复 | 本地已接入，私有远端已建立 |
| [0009](0009-task-evidence-and-actions-workflow.md) | 任务范围、证据与 GitHub Actions | bootstrap Actions已通过，M0 Actions待推送验证；CD待环境 |
| [0010](0010-m0-bounded-manifest-reader.md) | M0 有界 manifest 读取服务 | 接受，仅限单进程读取alpha |
| [0011](0011-m1-bounded-snapshot-serving.md) | M1 有界 Snapshot 服务化 | 接受，仅限单节点alpha；完整P0待后续 |
| [0012](0012-bounded-p0-and-local-workers.md) | 有界 P0 与本地 worker | 接受有界实现；后续分片范围由0013推进 |
| [0013](0013-local-p0-partitions-and-recovery.md) | 本地分片、记录版本与恢复 | 有界实现；完整M2/M3与生产证据仍缺 |
| [0014](0014-bounded-pg-wire.md) | 共用执行路径的有界 PostgreSQL SQL 端口 | 有界本机实现；真实 psql/Psycopg 及 PG 组件测试本地通过，最终提交门禁看 task receipt |
| [0016](0016-user-documentation-first.md) | 用户文档先行与场景验证 | 已接受工程约定；自动文件/链接检查与人工时序/语义复核分开 |
| [0017](0017-product-database-and-user-manual.md) | 产品级数据库交付与用户手册纠偏 | 接受产品组织原则；共同对象/目录/查询、用户旅程与手册深度待逐片实现验收 |
| [0018](0018-outline-design-and-module-contracts.md) | 概要设计基线与合同驱动的模块并行 | 接受责任与组织原则；端口schema、组件/性能/云/安全仍待实现验证 |
| [0019](0019-pr-parallel-development.md) | GitHub PR 与多分支并行开发 | 已采用工程约定；远端保护设置待另行授权和核验 |
| [模板](0000-template.md) | 后续决策的记录格式 | 模板 |

## 优先讨论的问题

| 顺序 | 问题 | 需要的结论或证据 |
| --- | --- | --- |
| 1 | 首批工作负载与规模 | 训练/推理/应用中的优先路径、数据集与可量化验收条件 |
| 2 | PostgreSQL 兼容与内核路径 | 已选 PG18 子集/HTTP 优先；补齐具体白名单、结果对照与 wire 验收范围 |
| 3 | 实现语言与工程结构 | 已选 Rust/Arrow/DataFusion POC；固定兼容依赖图、许可及公共类型/进程边界 |
| 4 | 统一逻辑数据模型 | 资产/片段/关系/向量、对象版本、跨模态关联及 schema 演进 |
| 5 | 快照与索引可见性 | 按 ADR 0004 细化状态机、失败对账、发布 fencing 与外部源保留 |
| 6 | 分布式元数据与存储 | PG 小控制面和对象事实层已为推荐基线；验证 catalog 服务、任务/分片、调度和故障模型 |
| 7 | 首批湖格式与连接器 | 版本、只读/写回、删除/快照语义、互操作测试 |
| 8 | 检索执行与优化 | 过滤、全文/向量融合、图遍历、近似误差与资源预算 |
| 9 | 身份与 Agent 安全边界 | 租户隔离、权限、查询预算、幂等/重试与审计 |
| 10 | 许可证与发布政策 | 依赖许可核查、项目授权、版本与兼容承诺 |

新增记录可复制 `0000-template.md`，采用下一个可用编号。尚待讨论的内容保持“提案”，决定后补齐依据和影响，再标“已接受”；被替代时链接新 ADR。

2026-10-18 的[功能与架构复审](../reviews/2026-10-18-capability-architecture.md)和[行动计划](../plans/2026-10-18-next-stage.md)不替代上述历史决定。后续执行面、持久布局或跨机运行时的选型经实测后再形成新ADR。

- [ADR 0015：严格生产源行覆盖与双接口场景](0015-unit-coverage-and-dual-interface-scenarios.md)：已采用测试门禁，覆盖率目标仍需实际证据达标；不扩展SQL产品白名单。
