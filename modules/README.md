# 模块地图

状态：对应技术架构v0.3的职责和当前代码落位；M0/M1有界alpha、部分M2/本地三worker和离线恢复已实现。更新日期：2026-10-18，见[实现复审](../docs/reviews/2026-10-18-implementation-and-tests.md)。

用户已确定对象存储湖架构、不做高并发 OLTP、不支持实时延迟敏感事务。本轮推荐 Rust + Arrow + DataFusion、Iceberg v2 + Parquet 事实层、Lance/Tantivy/邻接派生索引，以及 PostgreSQL 小型控制面；M0 Rust/Arrow/DataFusion/Parquet已有联编与有界互操作证据；M1/M2由Python/PyArrow与小型PG控制面承担，部分索引/增量已验收。完整M2质量、真实多机与生产发布仍待验证。

保留现有逻辑目录，不由目录直接推导新的部署服务。初期角色可以合并进程，资源池与实际拓扑按 POC 结果细化。

接入顺序统一以[路线图](../docs/roadmap.md)为准：M0 固定文件/只读 HTTP，M1 单源 Snapshot 与精确检索，M2 逐片增加 ANN/Graph/增量/托管 append，M3 真实分布式，M4 发布。模块职责是目标边界，不代表全部组件都是首个 alpha 的前置依赖；身份与保留依[数据合同](../docs/product/data-contracts.md)。

| 模块 | 负责 | 关键边界 |
| --- | --- | --- |
| [gateway](gateway/README.md) | HTTP 优先的查询/异步任务入口，PG18 SQL 子集、身份、预算与错误 | PG wire本机只读切片已独立验收；不继承完整PG事务与扩展 |
| [query](query/README.md) | M0 Rust SQL绑定/执行；M1/M2 Python固定视图job、检索融合 | 绑定 read view；补齐 PG 兼容、检索算子及分布式计划 |
| [catalog](catalog/README.md) | PostgreSQL 小型元数据、schema、权限、revision/read view、作业与发布 | 不存业务逐行数据；与外部 catalog 提交分开处理 |
| [storage](storage/README.md) | S3 对象访问、Iceberg/Parquet 数据与媒体引用、RAM/SSD 缓存、回收 | 对象持久层是恢复来源；本地缓存可丢弃 |
| [index](index/README.md) | Lance向量物化、v1 Tantivy/v2全局BM25、typed-edge一跳；邻接仍后续 | 固定源版本及稳定 ID，派生层不能独立双主写入 |
| [cluster](cluster/README.md) | 分片任务、exchange、资源池、背压、取消与恢复 | Ballista 等运行时待 POC；DataFusion 不自动提供分布式能力 |
| [connectors](connectors/README.md) | Iceberg REST Catalog、湖表、文件和训练数据集适配 | 托管首测 Iceberg v2 + Parquet；外部源能力逐格式/版本认证 |

建议依赖方向：客户端 → gateway → query → catalog / storage / index / connectors；cluster 为查询和后台任务提供执行与资源管理。DataFusion 计划、Arrow 批次、格式适配与索引接口的具体接线在 POC 中固定，避免循环依赖。

跨模块契约至少包含稳定逻辑 ID、租户/主体、data revision、read view、源快照、schema/索引版本、权限上下文、取消、资源预算与结构化错误。默认读已发布 read view；显式最新数据读取须正确补偿、等待或报错。

设计依据：[技术架构](../docs/architecture.md)、[产品功能架构](../docs/product/functional-architecture.md)、[检索与 Graph 调研](../docs/research/search-and-graph.md)。
