# 已发布数据库的产品架构与用户手册调研

访问日期：2026-10-19。目的：对照产品级数据库，纠正 GuraDB 用工程切片替代产品交付与用户文档的偏移。

## 1. 方法与证据边界

样本分三组：Milvus/Qdrant/Weaviate 的 AI 检索数据库，LanceDB/Vespa/Infinity 的多模态数据与组合检索系统，PostgreSQL/ClickHouse 的成熟数据库手册。它们范围不同，不能合成一个功能排名。

只使用官方文档、官方仓库及正式发布记录；没有安装竞品、性能/兼容测试或完整源码审计。以下产品事实是官方描述；“对 GuraDB 的启示”是本轮判断，不是厂商保证。动态文档、DEV、开源/商业/云版本分别标记。

选取的代表页检查了数据对象、操作前置、完整步骤、状态/输出、失败限制、预算/质量和生命周期。规模采用可复查的限定目录统计及官方目录，不把代码片段、语言副本或导航数当成用户页/功能数。

## 2. 产品范围与架构对照

| 产品与发行证据 | 可比较的用户对象与技术架构 | 不能误记的边界 |
| --- | --- | --- |
| [Milvus](https://github.com/milvus-io/milvus)、[正式发布记录](https://milvus.io/docs/release_notes.md) | collection/entity/vector；Proxy、Coordinator、Worker、Storage；WAL、对象存储和元数据协调读写 | Apache-2.0 核心与 Zilliz Cloud 分开；当前 3.0.x 文档不能套用旧2.x架构 |
| [Qdrant](https://github.com/qdrant/qdrant)、[releases](https://github.com/qdrant/qdrant/releases) | collection/point/vector/payload；segment 存储/索引、WAL、shard/replica、集群元数据共识 | Apache-2.0；Cloud 自动化与自托管维护分开 |
| [Weaviate](https://github.com/weaviate/weaviate)、[releases](https://github.com/weaviate/weaviate/releases) | collection/object/vector/tenant；shard 内对象/倒排/向量；metadata Raft 与数据复制分开 | 当前同仓含 Community 与 Enterprise；大部分 BSD-3-Clause，`wl/` 商业许可；同一二进制不等于所有能力开源 |
| [LanceDB](https://github.com/lancedb/lancedb)、[releases](https://github.com/lancedb/lancedb/releases) | table/schema/version/blob/embedding/index；Lance 上的检索与数据生命周期 | Apache-2.0 OSS 是嵌入式检索库；分布式 lakehouse 架构属于 Enterprise |
| [Vespa](https://github.com/vespa-engine/vespa)、[releases](https://github.com/vespa-engine/vespa/releases) | document/schema/tensor/rank profile/application；container/content/config clusters | Apache-2.0 自托管与 Cloud 托管运维分开；不是通用 SQL 湖数据库 |
| [Infinity](https://github.com/infiniflow/infinity)、[v0.7.4](https://github.com/infiniflow/infinity/releases/tag/v0.7.4) | database/table、dense/sparse/tensor、检索与多阶段 fusion；leader/follower/learner | Apache-2.0；DEV 文档不等于该正式 release 的逐项合同 |
| [PostgreSQL](https://www.postgresql.org/docs/18/index.html)、[许可](https://www.postgresql.org/about/licence/) | database/schema/table/type/role/transaction；成熟关系数据库与客户端生态 | 这里比较手册职责与精度，不把 OLTP 内核当 GuraDB 方向 |
| [ClickHouse](https://github.com/ClickHouse/ClickHouse)、[releases](https://github.com/ClickHouse/ClickHouse/releases) | table/engine/query/role/settings；列式分析、分片/复制与可观测性 | Apache-2.0；Cloud/特定引擎能力不外推为自托管通用能力 |

## 3. Milvus：湖上检索已是直接竞争范围

[架构页](https://milvus.io/docs/architecture_overview.md)分离访问、协调、worker 和持久层；streaming/query/data 职责及 WAL 与历史数据的关系都有专门说明。重要的比较单位是写入、建索引、查询与恢复的数据流，而非列出用了哪些库。

[Storage V3](https://milvus.io/docs/storage-v3.md)明确外部源只读，支持不同文件/表格式的 manifest，Iceberg 固定 metadata/snapshot 并保留 position-delete 信息；equality delete 不支持。新布局默认关闭，配置变更、旧数据后台转换和不能直接降级的边界写在同页。

[External Collection](https://milvus.io/docs/create-an-external-collection.md)给出 schema、字段映射、建集合、索引和刷新流程，还覆盖源凭据、异步状态与失败、源变化后的刷新责任。其文档不是“有一个 connector”式模块介绍。

**对 GuraDB：** “开放湖 + 向量 + 对象存储”不足以形成差异，早期研究其实已提醒这一点。应验证同一固定视图下 SQL 数据准备、检索证据和训练数据消费的价值。格式支持必须精确到读写方向、删除/schema/快照、认证与刷新；不能写一个格式名称便完成兼容合同。

**限制与反例：** 最新导航下的[扩容页](https://milvus.io/docs/scaleout.md)仍出现旧版本说明，[备份页](https://milvus.io/docs/milvus_backup_overview.md)矩阵未覆盖全部最新版本。本轮不将这些页推定为完整适配 3.0 的运维证明，也不从外部 collection 推导通用 SQL/Graph/训练产品。

## 4. Qdrant：边界集中，生命周期完整

[存储页](https://qdrant.tech/documentation/manage-data/storage/)将 point 的外部 ID、内部映射、版本、segment、向量/payload 存储与 WAL 恢复联系起来。[分布式部署](https://qdrant.tech/documentation/scaling/distributed_deployment/)区分拓扑/collection 元数据与 shard 数据复制。集群存在共识不等于业务数据拥有统一事务快照。

[一致性指南](https://qdrant.tech/documentation/scaling/consistency-guarantees/)分别解释写确认副本数、读一致性、写顺序及可用性代价，并说明部分失败可能已经应用，重试责任不能省略。[节点恢复](https://qdrant.tech/documentation/scaling/node-failure-recovery/)包含移除损坏 peer、加入节点、核对副本和补副本，并区分Cloud自动补足副本与自托管显式维护；不由此推导一般自动均衡能力。

[文档](https://qdrant.tech/documentation/)按开发、部署、生态、学习和 API 组织，point/vector/payload/collection 是用户概念。用户不需要先理解源码 crate。运维目录另有容量、快照、升级、安全、监控和诊断。

**对 GuraDB：** 每项操作都要定义结果、失败后是否有副作用、重试/对账以及完成验证；“增加 worker”“支持备份”不能替代具体管理合同。其 point/payload 与复制语义也不能代替 GuraDB 跨检索路径、分页和训练的固定 read view。

## 5. Weaviate：围绕对象、模型、租户与运行生命周期

[存储架构](https://docs.weaviate.io/weaviate/concepts/storage)说明 shard 中对象/倒排/向量结构及各自持久路径。[复制一致性](https://docs.weaviate.io/weaviate/concepts/replication-architecture/consistency)说明对象版本读与候选集合的区别：ALL 不会自动合并所有副本候选 UUID。不能把副本一致性旋钮当统一快照查询的证明。

[横向扩展](https://docs.weaviate.io/weaviate/concepts/cluster)和[备份指南](https://docs.weaviate.io/deploy/configuration/backups)均面向管理任务。后者覆盖提供商配置、发起/状态/取消/恢复、租户覆盖、目标已有 collection、恢复阶段、权限恢复默认等细节；这才足以让管理员判断恢复了什么、遗漏什么。

[文档首页](https://docs.weaviate.io/weaviate)区分 Database、Deploy 与 Cloud 等产品单元。结合[当前仓库许可说明](https://github.com/weaviate/weaviate)，本轮不把商业功能、Cloud/Agent 或外部模型服务并入 Community 能力。

**对 GuraDB：** 用户对象的创建、摄取、检索、隔离、演进、恢复与删除应构成完整叙事。模型集成不等于训练数据管理，备份 API 也不等于具备了带权限/媒体/pin 对账的恢复。

## 6. LanceDB：多模态必须具体到数据和读取行为

[产品首页](https://docs.lancedb.com/)明确 OSS/Enterprise 分界。[Enterprise 架构](https://docs.lancedb.com/enterprise/architecture)的 query nodes、plan executors、indexers、后台协调与对象存储可作 GuraDB 服务设计对照，但不能记为 OSS 分布式能力。[Enterprise quickstart](https://docs.lancedb.com/enterprise/quickstart)进一步区分 RemoteTable/LanceTable、服务 URI/存储路径、维护职责。

[Blob 指南](https://docs.lancedb.com/tables/multimodal)具体到 Arrow binary/large_binary、按需物化和不同查询/本地远端组合的限制。多模态不是在术语表里加图片、音频和视频，而是用户能预测读取的字节、内存和不支持操作。

[版本指南](https://docs.lancedb.com/tables/versioning)包含版本列表、checkout、restore、标签和清理。[索引维护](https://docs.lancedb.com/indexing/reindexing)解释未索引行的扫描补偿、仅索引模式的覆盖区别，以及 compaction/cleanup 的临时空间和保留后果。

**对 GuraDB：** 应把资产、片段、标签、特征和训练集的关系放到产品中心；URI/hash 和单个向量列只够证明组件输入。版本/索引新鲜度、按需媒体读取和维护成本都要成为用户可观察合同。不能直接引入 Enterprise 系统作为开源依赖。

## 7. Vespa：查询、排序和生产运维是一条产品链

[总体架构](https://docs.vespa.ai/en/learn/overview.html)区分处理请求的 container、存储/匹配/排序的 content 和配置管理集群。[近邻实践指南](https://docs.vespa.ai/en/querying/nearest-neighbor-search-guide.html)从样本、schema、feed 一直讲到 exact/ANN、过滤、hybrid、多路检索与质量/延迟选择。

[弹性](https://docs.vespa.ai/en/content/elasticity.html)讨论 bucket、副本、增减节点和故障补副本，拓扑影响吞吐与故障域；不能将其软性的 group 选择推定为 GuraDB 需要的固定视图分页。

[管理操作](https://docs.vespa.ai/en/operations/self-managed/admin-procedures.html)、[在线升级](https://docs.vespa.ai/en/operations/self-managed/live-upgrade.html)和[节点恢复](https://docs.vespa.ai/en/operations/self-managed/content-node-recovery.html)写清副本/容量前提、配置节点顺序、逐节点健康与同步检查，再继续下一节点。Cloud 运维能力单列。

**对 GuraDB：** 分布式要对应拓扑、故障域、分片/重平衡、权限传递和恢复完成条件；检索要对应共同候选—过滤—融合—回表/证据流程。三进程分发和几个独立 API 都不能代替这些验收。

## 8. Infinity：算子与组合语义具体，部署边界需谨慎

[搜索指南](https://infiniflow.org/docs/dev/search_guide)把结构化、全文、dense/sparse、tensor/multi-vector、多路召回与多阶段 fusion 放入具体模型，说明 RRF、权重、normalization 和过滤位置。它是查询合同的有用参考。

[集群指南](https://infiniflow.org/docs/dev/set_up_cluster)描述单 leader 写、最多四 follower 同步 WAL、多个 learner 异步 WAL、共享 MinIO、ADMIN 指派角色。不能据此声称多主、任意分片写或自动选主。[配置](https://infiniflow.org/docs/dev/configurations)具体到存储、端口、内存、线程、checkpoint/WAL 与维护周期。

[HTTP](https://infiniflow.org/docs/dev/http_api_reference)和[Python](https://infiniflow.org/docs/dev/pysdk_api_reference)参考列出参数/默认/失败与版本要求。访问时[DEV release notes](https://infiniflow.org/docs/dev/release_notes)落后于[正式 v0.7.4](https://github.com/infiniflow/infinity/releases/tag/v0.7.4)及部分配置示例，因此本轮仅引用 DEV 设计描述，不无条件把所有能力绑定到该 release。

**对 GuraDB：** 学习类型—索引—算子—融合—结果的精确定义，同时把 leader/目录/worker/存储职责和失败确认说明白。其文档与产品范围较集中，不宜成为生产运维深度的唯一模板。

## 9. PostgreSQL 与 ClickHouse：数据库手册的责任深度

[PostgreSQL 18 目录](https://www.postgresql.org/docs/18/index.html)有八大部分，编号章节延伸至 70，SQL/客户端/服务端命令另有参考；教程、语言、管理、客户端、服务端扩展、参考、内部实现和附录各司其职。这里只用这个固定主版本比较结构，不把它当 GuraDB 功能清单。

[SELECT 参考](https://www.postgresql.org/docs/18/sql-select.html)覆盖语法、处理顺序、参数、权限、兼容和示例；[备份](https://www.postgresql.org/docs/18/backup.html)将逻辑备份、文件备份、连续归档/PITR 分开并展开恢复前提。用户指南和内部机制可以同站，但不互相替代。

[ClickHouse 索引](https://clickhouse.com/docs/llms.txt)涵盖建模、格式、SQL/类型/函数/设置、接口、system tables 与管理。[备份](https://clickhouse.com/docs/concepts/features/backup-restore/overview)区分复制与误删恢复、全量/增量和异步状态；[权限](https://clickhouse.com/docs/concepts/features/security/access-rights)包含角色/配额/策略和拒绝例；[query_log](https://clickhouse.com/docs/reference/system-tables/query_log)逐列定义诊断证据；[自托管升级](https://clickhouse.com/docs/guides/oss/update)说明混合版本和顺序/降级边界。Cloud 与特定引擎另行解读。

**对 GuraDB：** 不要求复制所有 SQL 或 OLTP 能力，但已承诺的每项操作应有同样严谨的语义、参数、失败和恢复说明。日志位置、函数列表和 harness 报告不能代替数据库管理员手册。

## 10. 规模的可复查样本

| 样本 | 采样口径与结果 | 不能推导什么 |
| --- | --- | --- |
| 原 GuraDB 手册 | 起点 `09f53a2` 的 `docs/user/*.md`：9 文件、342 行、236 非空行、17,154 非空白字符 | 不是产品质量评分，字符含代码/表格/链接 |
| [Qdrant 官方文档源](https://github.com/qdrant/landing_page/tree/7e1d86802d29027d1d35b2170e3689ebd1740b62/qdrant-landing/content/documentation) | SHA `7e1d86802d29027d1d35b2170e3689ebd1740b62`；该目录 3225 个 `.md`，其中 `headless/` 2851 个，排除后 374 个 | 374 仍含云、导航/教程，不等于374个OSS任务；3225不能宣传成独立手册页数 |
| [Vespa 官方文档源](https://github.com/vespa-engine/documentation/tree/1fcad75f97f6bc6f707a05557a9c6774a2f7e3f5/en) | SHA `1fcad75f97f6bc6f707a05557a9c6774a2f7e3f5`；`en/` 下390个 `.html/.md/.mdx` blob | 含Cloud/商业与索引页；不等于390个自托管功能 |
| Milvus 官方目录 | v3.0.x 页面导航可观察12个一级域，含概念、数据导入、用户/管理指南、工具、教程、API | 导航数不是总页数或功能数 |
| PostgreSQL 18 | 固定主版本八大部分及细分参考体系 | 不能要求新项目机械达到同样页数 |

Qdrant/Vespa 通过官方 GitHub tree API 按 `type=blob`、路径与后缀统计，`truncated=false`；原始 JSON 在 `artifacts/product-research/*-tree.json`。复查可请求 `https://api.github.com/repos/<owner>/<repo>/git/trees/<上述SHA>?recursive=1`，按表内规则筛选；已固定 SHA，未来 HEAD 变化不改变本次口径。原手册统计可从 `git show 09f53a2:<path>` 复算。本次原始抓取不是全部网页的永久归档。

可观察的规模差距是**限定目录中的数百个文档文件，以及抽样确认的跨角色操作闭环**对比九个概述页，不能据文件数推导数百种职责或功能。深度样本包括：Milvus接入后如何刷新，Lance未索引行是否遗漏，Qdrant写失败如何重试，Weaviate恢复遗漏什么，Vespa何时继续升级下一节点。这些问题在GuraDB也必须有产品答案。

## 11. 研究结论与可推翻条件

1. GuraDB 目标应保持完整数据库，不能缩成索引作业或“湖上 HTTP 工具”。产品差异假设是共同版本/权限下的数据管理、SQL、检索证据和训练数据生命周期，尚未有业务样本证明市场价值。
2. 技术组件并不是用户对象模型；“一条记录一个向量加几个 URI”需演进为明确资产/片段/特征/关系合同。
3. 先收敛目录、身份、查询/作业上下文和执行语义，再增加接口或规模；不以一次全 Rust 改写作为捷径。
4. 湖事实层和可重建访问层可保留，但每份重复物化须用质量/成本/恢复证据证明，不能永久维护多套真值。
5. 用户手册按概念、教程、任务、参考和管理员职责重建；当前能力单列，不隐藏限制，也不让内部里程碑统治导航。
6. 产品验收与工程门禁都必需；覆盖率、三个worker、目录/链接检查均不能推出产品发布。

若首批工作负载无法证明统一产品价值，或版本/查询收敛成本不可接受，应以新 ADR 重评边界/组件；不能暗中缩小用户已经确定的产品目标。本轮不据文档比较承诺任何性能、规模或市场领先。

行动见[产品合同](../product/product-contract.md)、[方向复审](../reviews/2026-10-19-product-direction.md)和[交付计划](../plans/2026-10-19-product-delivery.md)。
