# Query

状态：技术架构 v0.2 的职责基线，推荐方案待 POC，未实现。

推荐以 Rust + Arrow + DataFusion 作为查询基础，复用向量化关系执行，自行补齐 PostgreSQL 18 SQL 子集的解析/绑定/类型与错误映射、检索扩展节点及分布式计划。依赖版本须通过联编 POC 后固定。

负责逻辑/物理计划、投影/谓词/文件裁剪、连接聚合、结构化过滤、全文/ANN/Graph 组合、全局 TopK、融合与资源预算。DataFusion 单节点执行能力不等于已经拥有分布式数据库。

从 catalog 固定 schema、data revision 与 read view，选择覆盖该视图的扫描/索引路径，通过 cluster 调度。默认读已发布视图；显式最新数据若不能在预算内补偿、等待索引，则报错。

全文/向量各路先进行跨分片合并，再按稳定逻辑 ID 去重和 RRF 融合；Graph 可作为过滤、扩展或证据算子。ANN 与精确结果、图预算截断及候选窗口必须可观察。

权限过滤尽可能进入候选生成，回表再次校验；旧索引不能搭配新记录而声称完整。分页延续固定视图与排序规则，取消和预算传递到全部远程任务。

POC 验收关系结果基线、PG 子集、过滤顺序、分片统计/TopK、融合排序、全局召回质量与取消传播；不承担高并发点事务。

设计依据：[技术架构](../../docs/architecture.md)、[产品功能架构](../../docs/product/functional-architecture.md)、[检索与 Graph 调研](../../docs/research/search-and-graph.md)、[查询接口](../../docs/interfaces/query-and-clients.md)。
