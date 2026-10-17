# Cluster

状态：以下是长期职责基线；当前已实现有界本地三进程 fanout，具体边界见 [本地worker](../../docs/design/m3-local-workers.md)，不能作为完整分布式验收。

用户要求面向海量数据的分布式系统。本模块负责节点/任务、分片路由、exchange/shuffle、资源隔离、背压、取消与故障恢复；原有目录不代表新增一组必须独立部署的服务。

推荐以 Rust/Arrow/DataFusion 为执行基础。Ballista 是分布式运行时参考/候选，Arrow Flight 等传输也需 POC；不能假定 DataFusion 单节点算子已经包含网络交换、spill、全局聚合/TopK 与可靠重试。

扫描任务按固定快照的文件/行组切分，检索按不可变索引 shard 调度，利用缓存亲和性；节点身份与数据/分片身份解耦。Graph frontier 采用批量跨分片交换，限制扇出及网络成本。

划分交互检索、训练扫描与索引/压缩后台作业的配额和队列，核算 RAM、SSD、网络、对象请求与任务预算。失败重试只能重算可重放阶段，输出不可变并以作业身份去重。

catalog 的 PostgreSQL 控制面负责小规模持久状态与发布权，cluster 配合租约/fencing/CAS 阻止失权 worker 提交。对象存储提供业务持久数据，缓存副本和索引可重建性不能代替元数据 HA 或备份。

POC 比较运行时的扩展计划节点、依赖版本、取消/重试及内存核算；验收必须包含多节点失败、网络中断、扩缩容、负载隔离和固定视图不漂移。单机模拟仅用于早期开发。

设计依据：[技术架构](../../docs/architecture.md)、[产品功能架构](../../docs/product/functional-architecture.md)、[检索与 Graph 调研](../../docs/research/search-and-graph.md)、[路线图](../../docs/roadmap.md)。
