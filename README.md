# GuraDB

面向 **AI 训练、推理与 AI 应用** 的分布式多模态一体化数据库。

GuraDB 的目标是在对象存储与开放湖上统一管理结构化数据、文本、图像、音频、视频、向量及关系数据，在同一查询体系内组合 SQL、全文检索、向量检索与 Graph 检索，并服务数据准备与可复现训练读取。

**当前仍是有界alpha，完整数据库产品尚未交付。** 从[用户手册](docs/user/README.md)了解场景、建模、接入、检索、训练和运行；当前可用操作见[能力白名单](docs/user/features.md)与[安装体验](docs/user/installation.md)。用户不需要先理解下方的内部M0/M1/M2阶段名。

2026-10-19完成[八个已发布数据库的产品与手册调研](docs/research/2026-10-19-database-products.md)及[方向复审](docs/reviews/2026-10-19-product-direction.md)。本轮纠正工程切片取代产品交付的偏移：[产品合同](docs/product/product-contract.md)与[架构v0.4](docs/architecture.md)要求共同对象、目录/权限/视图和查询语义，贯通数据管理、检索证据和训练消费。研究/文档修订没有新增运行时能力。

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

2026-10-18 [功能与架构复审](docs/reviews/2026-10-18-capability-architecture.md)、[A0集成复核](docs/reviews/2026-10-18-a0-integration.md)及[实现与测试复审](docs/reviews/2026-10-18-implementation-and-tests.md)保留历史代码/质量证据；[能力清单](api/capabilities/v1.json)是离线合同。下一阶段按[产品交付计划](docs/plans/2026-10-19-product-delivery.md)优先收敛对象/目录/查询与用户闭环，A1样本选择、A2按需读取、A3生命周期作为工程子任务继续推进。

## 用户文档

[用户手册](docs/user/README.md)按用户任务提供概念、数据建模、接入、检索、训练、安全、部署与参考，分别标注产品目标和当前alpha操作。完整可发布手册仍待补齐，见[建设合同](docs/user/manual-plan.md)。后续用户可见开发先写合同、再实现和验证，见[开发指南](docs/user/development.md)及[ADR0017](docs/decisions/0017-product-database-and-user-manual.md)。

## 从这里开始

1. [产品技术调研结论](docs/research/README.md)：竞品、方案比较、证据与取舍。
2. [产品功能架构](docs/product/functional-architecture.md)：12 个能力域、优先级与用户流程。
3. [技术架构 v0.4](docs/architecture.md)：共同对象/目录/查询、存储/索引、迁移与故障边界。
4. [数据湖格式矩阵](docs/compatibility/lake-formats.md)与[接口设计](docs/interfaces/query-and-clients.md)：兼容范围与协议。
5. [路线图与 POC](docs/roadmap.md)：M0–M4 切片、依赖与退出条件；alpha、分布式 P0、生产发布分别验收。
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

版本追溯已接入 [Git 工作流](harness/version-control.md)：切片提交、提交前检查、checkpoint 与独立目录恢复。已配置私有远端 [yizhouxw/guradb](https://github.com/yizhouxw/guradb)；用户已授权后续开发提交经验证后直接推送现有 `origin`，普通任务推送 `main`；不强推，远端设置与部署另行授权。

后续开发使用[任务与验收闭环](harness/development-workflow.md)，CI/CD 采用 [GitHub Actions 方案](harness/ci-cd.md)。此前 bootstrap CI 已远端通过；本轮 M0 工作流尚待推送后远端验证，CD 待发布产物和环境合同。
