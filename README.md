# GuraDB

2026-10-21 起按[模块交付策略 v2](docs/plans/2026-10-21-modular-delivery-v2.md)组织开发：[细粒度需求矩阵](docs/product/requirements-v2.md)、[模块 owner/输入输出/运行时权威](docs/design/module-delivery-contracts.md)与四层验证共同约束实施。机器门禁由独立 `gates-v2` 任务落地，文档不表示新用户能力已通过；当前先交真实共同视图查询，再推进图文和训练。

面向 **AI 训练、推理与 AI 应用** 的分布式多模态一体化数据库。

GuraDB 的目标是在对象存储与开放湖上统一管理结构化数据、文本、图像、音频、视频、向量及关系数据，在同一查询体系内组合 SQL、全文检索、向量检索与 Graph 检索，并服务数据准备与可复现训练读取。

**当前仍是有界alpha，完整数据库产品尚未交付。** 从[用户手册](docs/user/README.md)了解场景、建模、接入、检索、训练和运行；当前可用操作见[能力白名单](docs/user/features.md)与[安装体验](docs/user/installation.md)。用户不需要先理解下方的内部M0/M1/M2阶段名。

2026-10-20形成[概要设计v0.6](docs/design/outline-design.md)：从业务场景与[官方竞品证据](docs/research/2026-10-20-outline-design-evidence.md)推导业务、技术、模块、功能、部署架构，以及性能、可观测性、云适配、安全合规；配套[模块合同](docs/design/outline-module-contracts.md)和[并行实施计划](docs/plans/2026-10-20-parallel-delivery.md)。延续2026-10-19的[产品纠偏](docs/reviews/2026-10-19-product-direction.md)与[产品合同](docs/product/product-contract.md)，研究/文档修订没有新增运行时能力。

本轮[产品技术评审落实](docs/reviews/2026-10-20-product-review-followup.md)将首个样板收敛为企业图文知识库→带版本证据→同语料embedding/reranker训练评估，补充[训练样本与消费合同](docs/product/training-contract.md)、按需读取/质量成本门槛和早期纵向验收；决定见[ADR0020](docs/decisions/0020-product-review-and-vertical-delivery.md)。这些是目标与实施路径修订，当前alpha支持范围不变。

## 当前实现与评估入口

> M2 有界实现：append 源文件增量与稳定版本、物理 BM25/ANN 三分片、同机 HTTP worker、P0 并发负载和离线联合恢复，见 [M2 操作](docs/design/m2-running.md) 与 [实现范围](docs/decisions/0012-bounded-p0-and-local-workers.md)。完整 M2/M3 与生产发布仍有明确缺口；最终验证以本轮 commit 报告为准。

> M0/M1 基线阶段：单节点 alpha。M0 提供固定 Parquet manifest → Arrow/DataFusion → HTTP 只读 SQL；M1 增加有界 Iceberg v2 Snapshot → PG 发布目录 → BM25/精确向量/RRF → HTTP/CLI → 同视图训练导出。完整范围和最终本地证据见 [M1 设计与验收](docs/design/m1-validation.md)；后续能力见上述 M2 操作，尚不可生产发布。

M1 操作见 [Snapshot/检索/训练快速开始](docs/design/m1-running.md)。M0 SQL 服务见 [M0 快速开始](docs/design/m0-running.md)，支持边界见 [详细设计](docs/design/m0-parquet-http.md) 和 [验收映射](docs/design/m0-validation.md)。

PostgreSQL 客户端直连已实现有界本机切片：可选 PG SQL 端口复用 M0 只读执行与身份，真实 `psql` 18、Psycopg 3.2.10 及 PG 组件功能/性能/故障测试已本地通过。配置、SDK 示例与拒绝边界见 [PG 端口指南](docs/design/pg-wire-running.md)；它与 M1/M2 的内部 PostgreSQL 控制面是不同入口。最终提交的整项门禁与代码绑定证据以 task receipt 为准，组件通过不代表生产可发布。

## 已确定的方向

- 覆盖 AI 训练的数据准备与批量读取、推理的数据访问，以及 RAG、知识检索和 Agent 等应用场景。
- 多模态存储与检索一体化，支持关系、全文、向量、图及其组合查询。
- 面向海量数据的分布式架构，具备水平扩展方向。
- 对象存储湖架构，放弃高并发 OLTP，不支持实时延迟敏感事务；保留交互式检索、快照原子发布与故障恢复。
- 兼容主流开放数据湖与 AI 多模态数据格式；通过持续扩展的能力矩阵管理具体版本与读写边界。
- PostgreSQL 语法与客户端协议分别验收，提供 SQL 与 HTTP 接口，并便于扩展 CLI、MCP 客户端。

推荐目标栈为 **Iceberg v2/Parquet 事实层 + 媒体对象 + Lance 检索物化层，Rust/Arrow/DataFusion 执行，Tantivy 全文与有界 Graph，小型 PostgreSQL 控制面**。当前 M0 SQL 与 Python/PyArrow 的 M1/M2 检索作业分别运行；新 bundle v2 使用全局统计 BM25，旧 v1 保留 Tantivy 路径，ANN/Graph/增量/托管 append 已有有界切片。真实多机与生产发布仍待验证；PG wire 本机只读切片按 [ADR 0014](docs/decisions/0014-bounded-pg-wire.md) 独立实施与验收。

2026-10-18 [功能与架构复审](docs/reviews/2026-10-18-capability-architecture.md)、[A0集成复核](docs/reviews/2026-10-18-a0-integration.md)及[实现与测试复审](docs/reviews/2026-10-18-implementation-and-tests.md)保留历史代码/质量证据；[能力清单](api/capabilities/v1.json)是离线合同。下一阶段按[并行实施计划](docs/plans/2026-10-20-parallel-delivery.md)按共同读、接入生命周期、训练消费分批冻结合同，并提前验证共同查询、图文证据和实际训练消费；原产品交付与A1–A6验收义务保留映射。

## 用户文档

[用户手册](docs/user/README.md)按用户任务提供概念、数据建模、接入、检索、训练、安全、部署与参考，分别标注产品目标和当前alpha操作。完整可发布手册仍待补齐，见[建设合同](docs/user/manual-plan.md)。后续用户可见开发先写合同、再实现和验证，见[开发指南](docs/user/development.md)及[ADR0017](docs/decisions/0017-product-database-and-user-manual.md)。

## 从这里开始

1. [概要设计 v0.6](docs/design/outline-design.md)：场景、五类架构、关键技术和质量目标的完整入口。
2. [产品技术调研结论](docs/research/README.md)与[产品功能架构](docs/product/functional-architecture.md)：证据、取舍和12个能力域。
3. [技术架构参考](docs/architecture.md)、[模块合同](docs/design/outline-module-contracts.md)与[运行治理专题](docs/design/outline-runtime-and-operations.md)：实现边界与横切设计。
4. [数据湖格式矩阵](docs/compatibility/lake-formats.md)与[接口设计](docs/interfaces/query-and-clients.md)：兼容范围与协议。
5. [路线图与 POC](docs/roadmap.md)及[并行实施计划](docs/plans/2026-10-20-parallel-delivery.md)：M0–M4范围、工作包与退出条件；alpha、分布式 P0、生产发布分别验收。
6. [设计决策记录](docs/decisions/README.md)与[产品需求](docs/vision.md)：约束、选择与待验证事项。

完整导航见 [文档索引](docs/README.md)。

早期[实施设计复审](docs/reviews/2026-10-17-implementation-readiness.md)保留历史取舍；连接器与索引仍需遵循[记录身份、版本与保留合同](docs/product/data-contracts.md)。

## 仓库结构

```text
api/            M0 HTTP OpenAPI 与 manifest v1 schema
clients/        CLI、MCP 适配层的职责边界
docs/           调研、产品、架构、兼容性、接口、路线图与 ADR
crates/         M0 Rust workspace：common/storage/catalog/connectors/query/gateway
examples/       提案及 M0 示例（明确范围）
modules/        gateway/query/catalog/storage/index/cluster/connectors
scripts/        harness、固定构建和真实 M0 验收工具
harness/        agent 工作闭环、风险门禁、架构/不变量及证据协议
tests/          harness/契约、PG差异、S3/HTTP功能、组件性能/故障
```

## 本地检查

Python 3.11+、Git 和 Docker；Rust 通过固定容器构建，运行时验收用真实S3/PG容器。完整说明见 [Agent Harness](harness/README.md)。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock -r requirements-m0.lock -r requirements-m1.lock
.venv/bin/python scripts/harness.py install-git-hooks
.venv/bin/python scripts/harness.py plan
.venv/bin/python scripts/harness.py check
# 系统有可用 make 时等价入口：
make check
```

当前按风险执行仓库/架构、OpenAPI/契约、harness 自测、Rust fmt/clippy/test、Python编译/依赖、真实 M0/M1 功能/组件性能/组件故障，生成独立报告和日志。本地并发/60秒持续负载及恢复驱动已接入；完整 performance/stability/soak 尚未完成，`check --scope release` 预期失败。单独 `python3 scripts/check_repository.py` 仍可用标准库做最小文档检查。

参与设计与开发请先阅读 [贡献指南](CONTRIBUTING.md) 和 [Agent 协作约定](AGENTS.md)。

版本追溯已接入 [Git 工作流](harness/version-control.md)：切片提交、提交前检查、checkpoint 与独立目录恢复。已配置私有远端 [yizhouxw/guradb](https://github.com/yizhouxw/guradb)；用户已授权后续开发提交经验证后推送任务分支到现有 `origin`，并通过 [GitHub PR 并行流程](harness/parallel-development.md) 审查、验证后合入 `main`；不直接推送主线，不强推，远端设置与部署另行授权。

离线恢复由[PM START](harness/pm/START.md)进入[当前索引](harness/pm/START.md)、[本地任务](harness/tasks/README.md)及[成员记忆](harness/members/README.md)；规范见[ADR0025](docs/decisions/0025-local-member-memory-and-task-delegation.md)。GitHub Issue可选，普通分支/PR与本机质量义务保留。

后续开发使用[稳定成员、本地任务与有界委派](harness/team-collaboration.md)和[任务验收闭环](harness/development-workflow.md)。2026-10-24起按用户决定[暂停GitHub Actions CI/CD与PR远端CI准入](harness/ci-cd.md)，当前以本机自测、独立系统测试/复核和精确main证据保障合入；恢复CI/CD待项目完整度与环境条件明确后重新讨论。
