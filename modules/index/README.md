# Index

状态：技术架构 v0.3 的职责基线，推荐方案待 POC，未实现。

负责可重建的全文、向量与 Graph 访问结构及其构建/刷新；事实数据和关键模型特征由湖表/对象保存。推荐栈是 Tantivy、Lance 派生物化层和边表邻接结构，尚未完成联编、正确性和成本验证。

| 路径 | 分阶段推荐 | 复用边界 |
| --- | --- | --- |
| 全文 | M1 Tantivy BM25 与字段过滤；本地构建后封存上传，更多操作符独立验收 | 分布式路由、统计、缓存与发布由 GuraDB 实现；不自动兼容 PG 全文函数/Elasticsearch DSL |
| 向量 | M1 精确 flat 真值；M2 Lance IVF/PQ 独立 POC，图式索引作后续对照/热点候选 | 物化必要 embedding、稳定 ID/版本与过滤列，绑定独立 Lance dataset version；不与 Iceberg 双主 |
| Graph | M2 先受限边表一跳 join；邻接/分块 CSR 与更多有界跳数按测量增加 | ordinal 仅为版本内物理映射；不做完整 Cypher/GQL 或全图算法平台 |

每个 artifact 记录源 revision/快照、覆盖分片、schema、稳定逻辑 ID 映射、模型/分析器/算法与格式版本、参数、对象校验和及构建状态。Lance 内部 rowid、Parquet 行位置和图 ordinal 均不能成为跨格式业务身份。

源数据批量/显式小批提交后异步构建索引，完整上传并校验后交由 catalog 原子发布 read view；持续微批管道属 P1。默认查询固定已发布视图；追加/更新/删除补偿必须证明覆盖，不能用旧候选回表新记录冒充最新结果。

query 负责跨分片候选合并与 RRF；index 提供身份/版本、距离或分数、过滤能力、候选覆盖与证据。图遍历及 ANN 预算耗尽必须显式返回状态，权限撤销不能等待索引重建。

POC 验收更新删除、compaction/ID 映射、失败恢复、过滤后有效召回、全局 Recall@K、Graph 边界、冷热缓存与完整存储放大，不引用竞品单机数字承诺性能。

设计依据：[技术架构](../../docs/architecture.md)、[产品功能架构](../../docs/product/functional-architecture.md)、[检索与 Graph 调研](../../docs/research/search-and-graph.md)。
