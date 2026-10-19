# Storage

M0 当前实现见对应 `crates/guradb-storage`，仅限[有界读取设计](../../docs/design/m0-parquet-http.md)与[实际验收映射](../../docs/design/m0-validation.md)，下述长期职责不等于已支持。

状态：M0 Rust固定local/S3对象读取及Python显式root读取、依赖副本/不可变产物校验与fsync已实现，见[objects](objects.py)。当前不是RAM/SSD分层缓存、范围GET或通用对象GC系统；下文为长期职责，实际保留与回收边界见[M2操作](../../docs/design/m2-running.md)。

用户已确定基于对象存储的湖架构。推荐 S3 API 持久层、Iceberg v2 + Parquet 托管事实表、大媒体外置与版本化引用；格式具体读写能力仍需与 connectors 共同验证。

负责不可变数据/媒体/索引产物的对象访问、稳定身份与校验、读取抽象、内存/SSD 缓存和垃圾回收。Lance 物化数据、Tantivy 与邻接产物由 index 生成，storage 提供持久对象与缓存接口。

对象存储是业务数据和持久产物的恢复来源；本地 SSD 是可丢弃缓存。先验证不可变索引分片下载后本地打开，再评估 range GET/按页缓存；训练扫描采用批量读取、投影、预取与请求合并。

源表格式维护其内部 manifest，storage 不绕过协议直接改写。对象引用包含后端、位置、不可变 key/对象版本与完整性摘要；摘要不能让已被覆盖的旧字节重新可取，ETag 不无条件等于内容摘要，S3 兼容后端逐项认证。

区分托管数据与外部引用的所有权，并登记保留等级；本地 pin 不约束外部 vacuum。托管回收先原子标记 retiring 拒绝新 pin，再等待既有查询/训练/构建 pin、保留期与安全期，检查源格式引用后经维护协议清理。不能依赖 rename 或目录 LIST 重建事务状态，也不能仅因索引可重建就提前删掉仍被引用的产物，详见[数据合同](../../docs/product/data-contracts.md)。

POC 验收对象/范围读取、校验失败与权限撤销、冷/热缓存成本、限流背压、缓存丢失恢复与引用安全回收；不设计高并发点写主副本协议。

设计依据：[技术架构](../../docs/architecture.md)、[产品功能架构](../../docs/product/functional-architecture.md)、[检索与 Graph 调研](../../docs/research/search-and-graph.md)。
