# GuraDB

面向 **AI 训练、推理与 AI 应用** 的分布式多模态一体化数据库。

GuraDB 的目标是在对象存储与开放湖上统一管理结构化数据、文本、图像、音频、视频、向量及关系数据，在同一查询体系内组合 SQL、全文检索、向量检索与 Graph 检索，并服务数据准备与可复现训练读取。

> 当前阶段：M0 单进程读取 alpha。固定 Parquet manifest → 校验对象 → Arrow/DataFusion → HTTP 参数化只读 SQL；含真实功能、组件性能及故障门禁。多模态索引、Iceberg、写入和分布式按路线图继续实现，尚不可生产发布。

运行服务见 [M0 快速开始](docs/design/m0-running.md)，支持边界见 [详细设计](docs/design/m0-parquet-http.md) 和 [验收映射](docs/design/m0-validation.md)。

## 已确定的方向

- 覆盖 AI 训练的数据准备与批量读取、推理的数据访问，以及 RAG、知识检索和 Agent 等应用场景。
- 多模态存储与检索一体化，支持关系、全文、向量、图及其组合查询。
- 面向海量数据的分布式架构，具备水平扩展方向。
- 对象存储湖架构，放弃高并发 OLTP，不支持实时延迟敏感事务；保留交互式检索、快照原子发布与故障恢复。
- 兼容主流开放数据湖与 AI 多模态数据格式；通过持续扩展的能力矩阵管理具体版本与读写边界。
- PostgreSQL 语法兼容方向，提供 SQL 与 HTTP 接口，并便于扩展 CLI、MCP 客户端。

推荐目标栈为 **Iceberg v2/Parquet 事实层 + 媒体对象 + Lance 检索物化层，Rust/Arrow/DataFusion 执行，Tantivy 全文与有界 Graph，小型 PostgreSQL 控制面**。按[路线图](docs/roadmap.md)逐片接入：先固定 Parquet 文件读取，再做一个 Iceberg 源的 Snapshot、BM25/精确向量与训练闭环，随后加入 ANN、Graph、受限增量、托管 append 和真实多节点。M0 已验证有界 Parquet 读取与 PG18 SELECT 子集，其余能力待验证；PG18 SQL 子集优先，wire protocol 后续单独验收。

## 从这里开始

1. [产品技术调研结论](docs/research/README.md)：竞品、方案比较、证据与取舍。
2. [产品功能架构](docs/product/functional-architecture.md)：12 个能力域、优先级与用户流程。
3. [技术架构 v0.3](docs/architecture.md)：存储/计算、索引、数据发布与故障边界。
4. [数据湖格式矩阵](docs/compatibility/lake-formats.md)与[接口设计](docs/interfaces/query-and-clients.md)：兼容范围与协议。
5. [路线图与 POC](docs/roadmap.md)：M0–M4 切片、依赖与退出条件；alpha、分布式 P0、生产发布分别验收。
6. [设计决策记录](docs/decisions/README.md)与[产品需求](docs/vision.md)：约束、选择与待验证事项。

完整导航见 [文档索引](docs/README.md)。

本次[设计复审记录](docs/reviews/2026-10-17-implementation-readiness.md)说明修正原因；连接器与索引实现前先冻结[记录身份、版本与保留合同](docs/product/data-contracts.md)。

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
.venv/bin/python -m pip install -r requirements-dev.lock -r requirements-m0.lock
.venv/bin/python scripts/harness.py install-git-hooks
.venv/bin/python scripts/harness.py plan
.venv/bin/python scripts/harness.py check
# 系统有可用 make 时等价入口：
make check
```

当前按风险执行仓库/架构、OpenAPI/契约、harness 自测、Rust fmt/clippy/test、真实 M0 功能/组件性能/组件故障，生成独立报告和日志。完整 performance/stability/soak 尚未实现，`check --scope release` 预期失败。单独 `python3 scripts/check_repository.py` 仍可用标准库做最小文档检查。

参与设计与开发请先阅读 [贡献指南](CONTRIBUTING.md) 和 [Agent 协作约定](AGENTS.md)。

版本追溯已接入 [Git 工作流](harness/version-control.md)：切片提交、提交前检查、checkpoint 与独立目录恢复。已配置私有远端 [yizhouxw/guradb](https://github.com/yizhouxw/guradb)；本地新提交的推送需另行授权。

后续开发使用[任务与验收闭环](harness/development-workflow.md)，CI/CD 采用 [GitHub Actions 方案](harness/ci-cd.md)。此前 bootstrap CI 已远端通过；本轮 M0 工作流尚待推送后远端验证，CD 待发布产物和环境合同。
