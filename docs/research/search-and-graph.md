# 全文、向量、Graph 与湖上索引调研

状态：调研结论与技术提案，尚未实现或验证。调研日期：2026-10-17。

本文区分官方能力、工程推论与 GuraDB 建议；引用官方文档、项目源码说明或原论文。
动态文档与 `main` 分支仅作为调研证据，进入 POC 时必须冻结依赖版本、索引格式和配置。
相关总体边界见[总体架构](../architecture.md)；格式支持范围见[兼容矩阵](../compatibility/lake-formats.md)。

## 1. 对产品方向的直接结论

建议把全文、ANN 与 Graph 作为同一湖数据版本的**可重建派生索引**，共用身份、权限和查询计划。
对象存储保存权威数据与持久索引，worker 的 RAM/SSD 保存可丢弃的工作集；训练扫描与检索分别分配资源。
放弃高并发 OLTP 和 RT 敏感事务，使批量构建、微批提交、后台合并成为合理主路径。
这并不取消原子提交：数据快照、索引清单切换、删除可见性和恢复仍须有严格语义。

| 层 | 首版建议 | 明确边界 |
| --- | --- | --- |
| 权威数据 | 结构化字段、文本、边表、embedding 源版本由湖表管理；媒体保存稳定对象引用 | 索引不成为另一份可独立写入的主数据 |
| 全文 | 优先验证 Tantivy：BM25、布尔/短语、字段过滤及稳定身份回表 | 不承诺 Elasticsearch DSL 或 PostgreSQL 全文函数兼容 |
| 向量 | 精确扫描建立正确性基线；优先验证 Lance 物化层的 IVF_PQ，再对照 IVF_HNSW_SQ | 不能把 ANN 结果称为精确最近邻 |
| Graph | 节点/边关系表 + 按快照构建的出入邻接/CSR + 有界遍历 | 首版不实现完整 Neo4j、Cypher、全图算法平台 |
| 融合 | 各路完成全局候选合并后执行 RRF，随后可选重排 | 有限候选窗口不等于全集的精确融合排名 |

## 2. 全文：Tantivy 与 Lucene 的复用取舍

Tantivy 是 Rust 搜索库，以不可变 segment 和 WORM Directory 抽象组织索引；提交后文档可检索。
它提供 mmap/RAM Directory，但库本身不提供 GuraDB 所需的分布式目录、任务调度与湖快照协议。
依据：[Tantivy 库文档](https://docs.rs/tantivy/latest/tantivy/)、[Directory 文档](https://docs.rs/tantivy/latest/tantivy/directory/index.html)。

Lucene 是另一条成熟的库复用路径：reader 固定一个索引时点，segment 核心与每次提交的存活位图/更新共同定义可见性。
其 docid 在合并后会变化，官方明确要求将其视为内部实现标识。
依据：[Lucene 10.3.1 index API](https://lucene.apache.org/core/10_3_1/core/org/apache/lucene/index/package-summary.html)。

| 维度 | Tantivy 路径 | Lucene 路径 | GuraDB 取舍 |
| --- | --- | --- | --- |
| 集成边界 | Rust 库内嵌，Tokenizer/Query/Collector 可扩展 | JVM 库；若核心采用其他语言，需 JNI 或进程协议 | 核心若选 Rust，先做 Tantivy POC；语言决定前不将其写成已接受依赖 |
| 搜索能力 | BM25、布尔、短语、字段列式读取等可形成首版闭环 | 分析器、查询及索引扩展面较宽，需逐项验收所需能力 | 用中英混合、代码符号、短语和高亮需求评估，不能仅比较吞吐 |
| 对象存储 | 需要打包、缓存或自定义 Directory | 同样需要对象访问、缓存与发布协议 | 两者均不因有 Directory 抽象就自动具备低延迟 S3 搜索 |
| 更新/删除 | 业务 ID 字段 + 删除词项/存活位图 + 新 segment | 业务 ID 字段 + live docs/新 segment | 与源快照的更新删除集合核对，内部 docid 不对外持久化 |
| 分布式 | 自行实现分片、全局统计、候选合并、恢复 | 同样是库，完整产品能力须另建或采用上层系统 | 不把嵌入库误写为已经获得完整搜索服务 |

以上 Tantivy 的分词、合并和删除机制见[官方架构说明](https://github.com/quickwit-oss/tantivy/blob/main/ARCHITECTURE.md)。
建议首版在构建节点写本地索引，封存文件清单、校验和与版本后上传对象存储；查询节点下载所需分片到 SSD，使用本地 reader。
后续再验证按块/range GET 的 Directory，避免首版同时承担搜索算法、远程随机 I/O 与缓存一致性三类风险。
Quickwit 已采用对象存储 splits、metastore 发布与无持久主数据的 searcher，证明这类工程分层有参考实现；其具体时延不能直接移植为 GuraDB 指标。
依据：[Quickwit 架构](https://quickwit.io/docs/overview/architecture)。

分布式 BM25 还须统一或声明 IDF/文档长度统计口径；简单合并各分片使用不同统计计算的分数，会使排序随分片布局改变。
建议 POC 对照全语料单索引结果，决定使用快照级统计，或明确提供分片统计的近似相关性模式。
PostgreSQL 的 `tsvector`、`tsquery`、`@@`、`ts_rank` 有自己的类型与词法语义；采用 BM25 不等于兼容这些行为。
依据：[PostgreSQL 18 全文控制](https://www.postgresql.org/docs/18/textsearch-controls.html)。

## 3. ANN：算法适配、介质与库实现必须分开判断

| 路径 | 算法/介质特点 | 可复用部分 | 湖架构中的风险与定位 |
| --- | --- | --- | --- |
| Flat 精确扫描 | 不训练、不近似，读全部符合条件向量 | Arrow/列式扫描及向量距离算子 | 作为小数据、强过滤和 ground truth；不能对海量在线查询无限回退 |
| HNSW | 多层邻近图，查询沿图访问候选 | 成熟库中的构建、搜索和序列化 | 热数据 RAM/SSD 可选；把每次邻接跳转变为 S3 GET 会放大请求与尾延迟，此为介质推论而非算法禁止 |
| IVF_FLAT / IVF_PQ | 先选择聚类分区，扫描分区中的原向量或压缩码 | 聚类、PQ、分区扫描、候选精排 | 分区读取更易合并/预取；仍需训练、调 `nprobes`，量化与分区裁剪均可能损失召回 |
| IVF_HNSW_SQ | IVF 分区内使用图及标量量化 | Lance 对应组合的构建/搜索 | 是复合索引，不能直接等同于一个全局 HNSW；对照质量、RAM 与冷读成本 |
| DiskANN / Vamana | 原论文面向 SSD 驻留的图搜索与内存压缩信息 | 官方索引库、构建及 SSD 搜索路径 | 更适合作为 SSD 工作集候选；对象存储可持久保存文件，不代表原生逐跳远程对象查询 |

依据：[HNSW 原论文](https://arxiv.org/abs/1603.09320)、[Lance 向量索引格式](https://lance.org/format/index/vector/)、[DiskANN 原论文与介质说明](https://www.microsoft.com/en-us/research/?p=634449)。
Faiss 的 on-disk IVF 使用本地文件 mmap，并支持倒排列表预取；它不是开箱即用的 S3 range reader。
Faiss 文档也指出 on-disk 列表的增量追加成本较高，批量构建合并更合适。
因此可将 Faiss 用作算法与成本基线，不能把 `IO_FLAG_MMAP` 当作湖索引实现。
依据：[Faiss on-disk 设计](https://github.com/facebookresearch/faiss/wiki/Indexes-that-do-not-fit-in-RAM)、[OnDiskInvertedLists API](https://faiss.ai/cpp_api/struct/structfaiss_1_1OnDiskInvertedLists.html)。

首版建议只暴露可解释的距离类型、向量维度/空间、过滤、TopK 与质量预算；具体索引类型由配置或管理员选择。
同一向量空间必须记录模型、模型版本、归一化规则、精度和距离函数；不同模型的原始距离不能直接比较。
先以 IVF_PQ 验证成本优势，再用 IVF_HNSW_SQ 对照精度与资源；若量化误差不能通过候选精排补足，再调整默认路径。
DiskANN 保留为后续 SSD 方案 POC，不让首版同时维护多套 ANN 文件格式、删除机制与分布式实现。

## 4. Lance ANN 复用：优先采用最小派生物化表

Lance 向量索引将 IVF、分区内结构与量化分别定义，当前官方格式文档描述索引版本 3；库版本和索引版本须分别固定。
向量格式可读不等于任意引擎能正确使用：还需要 dataset manifest、字段、覆盖片段、删除及行身份解析。
依据：[Lance 向量格式](https://lance.org/format/index/vector/)。

建议流程是 `源湖表快照 → Arrow 批次 → Lance 派生 dataset → 构建 ANN → 固定 dataset version → 发布 GuraDB artifact manifest`。
首版物化 `record_id/segment_id`、`source_version`、embedding、向量空间和必要过滤字段；媒体、全文大字段和所有业务列无需全部复制。
Iceberg 等源表仍是写入与版本权威，Lance dataset 只接收派生任务写入，客户端不能直接更新它。
查询用 Lance scanner 返回稳定业务身份，再从源快照或经验证的覆盖列读取结果；可把小型证据列加入物化层降低回表成本。

不建议首版只抽取 `index.idx`，直接将其中行号解释成 Parquet 行号：Lance index segment 绑定 dataset version 与 fragment 覆盖，删除、更新和 compaction 有独立规则。
官方还将基于稳定行 ID 的索引路径标为 experimental；GuraDB 不能把它作为跨格式业务身份保证。
依据：[Lance 索引与 compaction 规范](https://lance.org/format/index/)。
GuraDB 自有稳定 ID 必须独立于 Lance `_rowid`、fragment offset 和源文件 row position；物理映射只在绑定版本内有效。
若后续希望直接复用 Lance 的索引算子而省去向量副本，需要验证独立构建接口、ID 映射、预过滤、删除位图、精排回读与升级兼容；这属于新增集成项目。

这一建议有明确成本：源向量与 Lance 列可能重复保存，另加压缩索引、映射、过滤列、历史版本和构建临时空间。
POC 应分别计量 `权威数据 + 派生数据 + 索引 + 历史保留 + 临时峰值 + SSD缓存`，不能仅报告 PQ 码长度。
若复制成本不可接受，备选是直接在源扫描接口上实现独立 IVF artifact；代价是自行维护格式和搜索/过滤协议。
训练随机样本读取可选使用 Lance 物化数据，但必须量化额外复制的收益，不能要求所有湖数据预先转换成 Lance。

## 5. Graph：边表、邻接物化与有界遍历

首版建议把 property graph 映射为普通节点表、边表与图视图定义，边具有独立 `edge_id`、类型、方向、属性和来源证据。
派生索引按 `(graph_version, source_node_id, edge_type)` 组织出邻接；入邻接另建，避免反向遍历反复扫描全边表。
可将邻接保存为分块 CSR，块内用稠密 ordinal 压缩，另存稳定节点 ID 与 ordinal 的版本化映射。
CSR 和邻接块是执行布局，不能将 ordinal 用作对外节点身份，也不能在重建后复用旧 ordinal。
关系表与 CSR 结合有 DuckPGQ 的原论文参考，但该 DuckDB 扩展不是现成的分布式 Graph 内核。
依据：[DuckPGQ 原论文](https://www.vldb.org/pvldb/vol16/p4034-wolde.pdf)。

| 首版范围建议 | 暂缓范围 | 必须明确的语义 |
| --- | --- | --- |
| 按属性找节点、指定类型/方向的一跳和有界多跳扩展 | 无界任意路径枚举 | 最大深度、扇出、访问边数、内存与超时 |
| 从全文/向量候选扩展证据子图 | 全功能 Cypher/GQL 兼容 | 路径是否允许重复节点/边、多重边、去重与排序 |
| 节点/边过滤、路径证据、可选有界可达性 | 分布式全图中心性、社区发现、全图训练引擎 | 节点删除、悬空边、边/节点版本及权限处理 |

PostgreSQL 18 提供 `WITH RECURSIVE`、`SEARCH`、`CYCLE`，可以表达关系上的递归；`SEARCH` 排序列不保证物理访问顺序。
外层 `LIMIT` 也不能代替可靠的遍历预算，尤其遇到排序或 join。
依据：[PostgreSQL 18 递归查询](https://www.postgresql.org/docs/18/queries-with.html)。
PostgreSQL 18 的原生 `SELECT` 语法未提供 SQL/PGQ `GRAPH_TABLE`；因此 PG18 语法兼容不自动带来 SQL/PGQ，后续 PostgreSQL 版本需另行评估。
依据：[PostgreSQL 18 SELECT 语法](https://www.postgresql.org/docs/18/sql-select.html)。
SQL/PGQ 的图视图/模式匹配是后续可选入口；首版可先定义关系查询和受限图算子，之后选择语法映射。
DuckPGQ 展示了 `CREATE PROPERTY GRAPH` 与 `GRAPH_TABLE`，但它自己的语法覆盖也有边界，不能直接称为全部标准实现。
依据：[DuckPGQ SQL/PGQ 文档](https://duckpgq.org/documentation/sql_pgq/)。
Neo4j/Cypher 可作为 property graph、方向与路径模式的产品参考；不据此承诺兼容 Cypher 或其事务/优化行为。
依据：[Neo4j 节点与关系模式](https://neo4j.com/docs/cypher-manual/5/patterns/reference/node-and-relationship-patterns/)。

Graph worker 按邻接块批量取 frontier，按节点归属分发下一轮，避免每条边一次 RPC 或对象 GET。
超大度节点、跨租户边和跨分片热点需专门限制；达到预算应返回明确截断状态或错误，不能把截断结果标为完整可达集或全局最短路径。
未经授权的节点/边不能成为返回路径及评分证据；先遍历完整图、最后删除隐藏节点可能泄漏关系并改变路径含义。

## 6. 统一身份、read view 与索引发布

建议 artifact manifest 至少记录以下契约；字段名仍为设计建议：

| 契约 | 必要内容 |
| --- | --- |
| 来源 | 数据集 UUID、源格式与版本、表快照/媒体对象版本、Schema/字段 ID |
| 覆盖 | 分片/片段集合、记录版本范围、更新删除覆盖、特征空间 |
| 算法 | 索引类型、库/格式版本、训练样本版本、参数、分词器/字典/模型版本 |
| 产物 | 不可变对象地址、长度、校验和、业务 ID 映射、依赖产物 |
| 发布 | build ID、期望基版本、提交状态、构建完成与发布时刻、保留引用 |

“有稳定 ID”只能防止认错记录，不能证明内容仍有效：索引旧 embedding 对应的 ID 可能在新快照变更文本、向量或权限。
对追加缺口可扫描未索引片段并合并；更新必须排除旧项并重新计算新项，删除必须在召回阶段应用可见性信息并在回表复核。
仅将旧候选与新表 join 会漏掉更新后新进入 TopK 的记录；过滤掉已删除命中也可能造成不足 K，必须补取或声明预算耗尽。
Lance 自身区分 indexed/unindexed fragments、删除过滤与 compaction remap，提供了可参考的覆盖模型；跨源覆盖仍由 GuraDB 负责。
依据：[Lance 索引规范](https://lance.org/format/index/)。

查询开始时固定 `read_view_id = {source_snapshots, selected_artifacts, graph_version, policy_context}`；分页与重排延续该视图。
多个外部源的版本向量不意味着它们来自同一事务时点；结果应返回逐源版本与新鲜度，不声称跨源原子快照。
结合本轮架构取舍，默认绑定已发布的完整 read view，显式披露它相对已提交数据的滞后；只有显式请求 `data_committed` 时才绑定最新已提交数据，所需索引未覆盖则等待、在预算内正确补偿或报错。
不要使用一个含糊的 `eventual consistency` 开关替代全文/向量/Graph 各自的覆盖与缺口说明。
权限撤销需按服务安全策略及时生效，不能因为旧数据视图或索引缓存而继续授权；结果缓存应包含主体/策略版本并支持失效。

构建流程建议：读取固定源快照 → 写新对象 → 校验数量/覆盖/删除 → 上传并验证 → 原子发布新 manifest → 更新调度可见状态。
发布时校验期望基版本或 fencing token，拒绝失去任务所有权的 worker 覆盖新产物；重试以 build ID 幂等。
源数据提交和索引发布是两个提交点；查询通过显式覆盖策略连接两者，不需要跨 Iceberg/Lance/全文文件建立同步双写事务。
旧对象回收须等待活跃查询、分页游标、训练固定版本与历史保留引用释放；缓存丢失应能从持久对象恢复。

## 7. 过滤、融合与分布式全局 TopK

过滤是检索语义的一部分。租户、ACL、时间、模态、语言及业务谓词应尽可能在候选选择前生效；回表仍须复核权限。
不能用未经许可的候选占满 TopK 后仅在最后过滤，并向用户声称得到了授权子集内的最佳 K 条。
Lance 显式区分 prefilter/postfilter，后者可能返回少于 K；Milvus 也区分标准预过滤和迭代过滤。
这些模式提供工程参考，但预过滤本身并不把 ANN 变为精确搜索。
依据：[Lance scanner 参数](https://lance-format.github.io/lance-python-doc/index-and-search.html)、[Milvus filtered search](https://milvus.io/docs/filtered-search.md)。

建议优化器依据选择性与预算选择：小授权集合精确扫描、索引支持的预过滤、迭代补取，或在无法保证授权隔离时拒绝该计划。
复杂 ACL 从权威权限系统解析为版本化位图/集合；为其单独设计撤销失效，不能只复制一份永不更新的 ACL 列。
共享全文统计、缓存和图解释也需检查租户隔离；首版优先以租户边界分片并隔离缓存键，避免把全局统计直接解释给租户。

每路召回先搜索全部相关分片，再全局合并候选；距离函数、模型、归一化规则及全文统计必须可比较。
精确、无重复且分数可比较时，所有分片各返回本地 K 足以合并全局 K；ANN 的候选遗漏、过滤、更新与路由剪枝会破坏这个前提。
因此需要可调每片候选预算、probe/搜索宽度、补取与精排，并测量**集群全局** Recall@K；扩大候选不是召回保证。
未经正确性证明的向量分片路由只能作为近似模式；应记录探测覆盖，不能悄悄跳过可能含最近邻的分片。

建议首版 RRF 为 `score(d) = sum(1 / (rank_constant + rank_i(d)))`，名次从 1 开始；未进入某路窗口的记录该路贡献为 0。
BM25 分值、向量距离与图证据分值不直接相加；Graph 默认作为过滤/候选扩展，只有定义了明确图排序才作为第三路 ranked retriever。
原理依据：[RRF 原论文](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)；工程参考：[Elasticsearch RRF 的全局窗口与协调器融合](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)。
先融合分片本地 RRF 再合并，会把局部名次误当全局名次；正确基线是先取得各路全局窗口，再统一去重融合。
查询契约须固定每路窗口、rank constant、融合版本、去重单位（segment 或 asset）、同分稳定 ID 排序，以及窗口内分页边界。
RRF 只重排已经召回的候选；不修复 ANN 漏召回，也不证明 RAG 答案正确。重排模型须记录版本、成本预算和证据来源。

## 8. 进入详细设计前的 POC 门槛

以下是验收实验要求，数值规模是试验建议，不是已验证性能或交付承诺。

| 实验 | 至少覆盖 | 通过门槛 |
| --- | --- | --- |
| 全文库选择 | 中英混合/代码/短语，单片与多片，同一快照的更新删除 | 功能语义与单片基线一致，解释分词及分片统计差异，明确未覆盖语法 |
| ANN 质量/成本 | 建议百万、千万级开始；资源允许后扩大；多维度/模型/偏斜与分布漂移 | 用同快照精确扫描生成 ground truth，报告 Recall@K、存储/RAM/SSD、构建峰值与成本曲线 |
| 冷热与过滤 | 清空缓存、热缓存、缓存小于工作集；过滤选择性从极低到全匹配 | 分开记录 P50/P95/P99、GET 数/字节、过滤后不足 K、补取与超时，不混用冷热结果 |
| Lance 派生层 | 初次物化、增量、更新删除、源与派生 compaction、库/格式升级 | 无身份错配或删除泄漏；映射与快照可复现；完整计量向量副本及历史存储 |
| Graph | 环、多重边、悬空边、超大度节点、跨片 frontier、ACL 与预算中止 | 与小图参考遍历一致；截断可见、无越权路径、返回稳定证据 ID |
| 发布/恢复 | 构建或上传中断、发布冲突、worker 失权、缓存全丢、查询中版本切换 | 无半发布索引、旧任务不覆盖新版本、固定视图不漂移，可从对象存储恢复 |
| 负载隔离 | 训练扫描 + 索引构建 + 在线混合检索并行 | 可观察队列、带宽与缓存争用，取消传播、配额和资源隔离有效 |

POC 开始前为目标工作负载确定质量、索引新鲜度、尾延迟与单次查询成本预算；达到哪一组预算再决定默认算法和分片粒度。
公开论文或竞品单节点数字不能代替本项目的对象存储、权限过滤、混合排序与跨片测试，也不能据此承诺 PB 规模或毫秒级 SLO。
建议后续 ADR 分别记录：全文库、向量派生层边界、默认新鲜度策略、Graph 语法范围、索引 manifest 与兼容升级策略。
