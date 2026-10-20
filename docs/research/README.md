# 产品与技术调研结论

2026-10-20新增[概要设计官方证据矩阵](2026-10-20-outline-design-evidence.md)，以稳定R编号记录业务场景、产品/edition事实、设计推论、目标和反证验证，支撑[概要设计v0.5](../design/outline-design.md)与[并行实施计划](../plans/2026-10-20-parallel-delivery.md)。本轮仍为文档研究，无竞品部署或性能对跑；云与安全控制不代表适配/认证已完成。

最新补充：[2026-10-19已发布数据库的产品架构与用户手册调研](2026-10-19-database-products.md)，覆盖Milvus/Qdrant/Weaviate/LanceDB/Vespa/Infinity/PostgreSQL/ClickHouse，包含官方来源、版别边界、限定目录统计与任务页深度。其[方向复审](../reviews/2026-10-19-product-direction.md)和[产品合同](../product/product-contract.md)已修正执行主线。下文保留2026-10-17的技术选择背景，不能当作当前实现状态或最新任务顺序。

状态：基于官方资料的研究与推荐基线，未部署竞品、未进行性能或兼容性实测。日期：2026-10-17。

本轮将用户的新约束落实为：**对象存储作为业务持久层，面向 AI 数据准备、训练读取与交互式检索，不承担高并发 OLTP 和实时延迟敏感事务。** 明确约束见 [ADR 0002](../decisions/0002-object-store-lake-boundary.md)。

## 1. 建议产品定位

建议将 GuraDB 定义为 **面向 AI 数据生命周期的分布式多模态湖数据库**。产品重点是：在开放湖和对象数据上，统一多模态身份、版本、处理血缘、训练样本与关系/全文/向量/Graph 查询。

这不是已经验证的市场空白。LanceDB 已覆盖多模态训练与检索，Milvus 3.0.x 已提供外部湖数据查询路径。仅以“多模态 + 向量 + 对象存储”定位，区分度不足。[LanceDB 官方产品文档](https://docs.lancedb.com/)、[Milvus 外部集合](https://milvus.io/docs/create-an-external-collection.md)。

本轮选择的差异化验证点是：同一版本的数据能否完成 SQL 数据准备 → 训练样本发布 → 全文/向量/业务图检索 → 来源证据追溯，并在外部源变化和索引滞后时保持可解释的一致语义。这是待验证的产品假设，不是竞争优势结论。

## 2. 调研范围与证据

| 专题 | 重点对象 | 产出 |
| --- | --- | --- |
| [AI 数据与检索产品](ai-data-and-retrieval.md) | Lance/LanceDB、Milvus、Qdrant、Weaviate | 训练/检索能力、部署形态、湖路径及差异化假设 |
| [执行引擎与生态](execution-and-ecosystem.md) | DataFusion/Ballista、DuckDB、Velox、Trino，StarRocks/Doris/ClickHouse | 执行栈选择、PG 兼容缺口、分布式运行时和复用边界 |
| [对象存储与湖格式](lake-storage.md) | S3、Iceberg、Lance、Delta、Hudi、REST Catalog/Polaris | 权威数据、物化布局、提交/发布与生命周期 |
| [检索与 Graph](search-and-graph.md) | Tantivy/Lucene、IVF/PQ/HNSW/DiskANN、Lance、关系图/CSR、RRF | 索引路径、稳定 ID、过滤/融合、对象 I/O 与验证门槛 |

关键事实使用官方规范、项目文档或原论文就近引用；产品形态和版本边界写在对应专题。`latest`、`main`、`current` 页面会变化，具体实现前必须固定版本和测试样本。本轮没有采用厂商 QPS/延迟宣传作为选型依据。

## 3. 研究得到的架构取舍

| 问题 | 本轮选择 | 理由与代价 |
| --- | --- | --- |
| 是否构建 OLTP 内核 | 不构建高并发点事务数据面 | 减少逐行 WAL/锁/同步索引路径，换成批量提交与可见索引滞后；原子发布和恢复仍保留 |
| 业务数据存在哪里 | 对象存储，托管表先用 Iceberg v2/Parquet，媒体外置 | 开放表与批量扫描为基础；随机检索需要额外缓存/布局 |
| 是否全部使用一种格式 | 不强制；每份逻辑事实只有明确的权威来源 | 外部数据保留原格式；兼容和物化不等于同步双主 |
| AI 检索布局 | 首选验证 Lance 派生数据集 + 独立全文/邻接索引 | 复用成熟访问结构，承担向量/部分列冗余和版本映射成本 |
| SQL 执行基础 | Rust + Arrow + DataFusion 首选 POC | 适合扩展统一计划；服务器、PG 兼容和分布式仍有显著工作量 |
| 分布式基础 | 评估 Ballista 构件，并保留 Trino 对照路线 | 不把单节点引擎或样例集群当作生产分布式实现 |
| 全文与 Graph | Tantivy；边表 + 邻接物化 + 有界遍历 | 先完成可用组合检索；跨 shard 统计/路径和发布由 GuraDB 承担 |
| 默认一致性 | 固定已发布 read view，数据提交与索引就绪分开 | 容许显式滞后，减少不完整候选；最新读取需等待/补扫与预算 |
| 元数据权威 | 独立 PostgreSQL 控制面，REST Catalog 适配 | 复用小规模强一致事务，不自研共识；需独立 HA/备份且不保证所有未来规模 |
| 接口路线 | HTTP 与 PG18 SQL 子集优先，wire protocol 单列后续阶段 | 优先服务程序/Agent；完整 PG 扩展和 OLTP 行为不在范围 |

这些结论是基于本项目约束的工程判断。具体比较、反例和失败时的替代路线在专题中给出；不能据此宣称 DataFusion、Iceberg 或 Lance 比其它选择普遍更快。

实施顺序经[设计复审](../reviews/2026-10-17-implementation-readiness.md)修正，以[路线图](../roadmap.md)为准：目标栈按切片接入，M1 先验证精确向量与 Snapshot，M2 再分别引入 Lance ANN、受限 Graph、增量和 writer。本文及专题中的整体技术比较不作为所有组件同时进入首个 alpha 的要求。

## 4. 为什么不直接拼接三个数据库

独立全文、向量和图数据库可以很快提供单项能力，但会把源身份、更新/删除、索引覆盖、授权与快照对齐交给应用层。GuraDB 的目标恰好是统一这些边界，因此推荐复用引擎库/索引构件，服务层保留共同查询计划和发布协议。

这条路线的成本是内核工程：全局 Top-K、图跨分片、查询取消、缓存、shuffle、权限过滤和索引发布均需要设计。若 POC 显示这些成本超出团队可接受范围，应转向“成熟湖 SQL + 有界外部检索服务”的产品形态，并重新评估一体化承诺。

## 5. 当前已确定与仍需验证的内容

| 层级 | 内容 |
| --- | --- |
| 用户已确定 | 多模态、全文/向量/Graph、分布式、湖生态、PG 语法与 SQL/HTTP/CLI/MCP；对象存储湖架构；不承担高并发 OLTP/实时敏感事务 |
| 本轮推荐基线 | Iceberg v2/Parquet、Lance 派生层、Rust/Arrow/DataFusion、Tantivy/邻接结构、PG 小控制面、默认已发布视图 |
| POC 后确定 | 具体依赖联编版本、writer 能力、Lance 物化成本、ANN参数/布局、分布式运行时、首批 catalog 实现 |
| 工作负载确定后设定 | 目标规模、检索质量、冷热 p95/p99、新鲜度、训练吞吐、资源/成本、恢复目标 |
| 明确不承诺 | 全 PG 行为/扩展 ABI、所有格式任意读写、硬实时事务、跨外部源全局事务、无限图遍历、未经实测的规模与性能 |

技术基线可以被验证结果推翻。记录风险和替代路线是选择的一部分，不意味着本轮仍未作选择。

## 6. 应先验证的风险

1. **开放事实层与检索回表成本。** Parquet 小范围随机读取和对象 I/O 可能抵消检索优势；验证最小列物化、批量回表和冷热缓存。
2. **组件版本组合。** Arrow/DataFusion/Iceberg/Lance 的 crate/API 版本与类型可能不一致；先联编再决定依赖，必要时测量 IPC 桥接成本。
3. **快照/删除正确性。** 源快照变化、row position 重写、旧索引、外部 vacuum 和权限撤销必须在同一验证链路出现。
4. **发布与失败恢复。** 表提交、GuraDB 目录发布和索引发布不在一个跨系统事务中；在每个边界注入崩溃和重复执行。
5. **分布式检索与训练干扰。** 图 fan-out、ANN 过滤、全局融合、后台构建与训练扫描可能争用缓存/对象带宽，必须联合测试。
6. **产品区分度。** 对照最新 LanceDB/Milvus，以完整工作流、可解释版本和开发者接口验证价值，不能只比较功能勾选数量。

## 7. 本轮形成的架构文档

- [产品功能架构](../product/functional-architecture.md)：12 个能力域、优先级、用户流程和非目标。
- [技术架构 v0.4](../architecture.md)：本轮纠偏与历次存储/物化、发布、查询及故障基线。
- [技术基线 ADR](../decisions/0003-storage-and-execution-baseline.md)：选项与选择理由。
- [快照与索引发布 ADR](../decisions/0004-snapshot-and-index-publication.md)：最关键的一致性不变量。
- [路线图与 POC](../roadmap.md)：验证顺序、失败时的调整及首版范围。

本轮交付是有证据支撑的产品/技术架构基线。下一步应进入关键连接点 POC，而不是直接同时实现所有格式、协议、图语言与分布式事务。
