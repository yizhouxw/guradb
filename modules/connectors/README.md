# Connectors

M0 当前实现见对应 `crates/guradb-connectors`，仅限[有界读取设计](../../docs/design/m0-parquet-http.md)与[实际验收映射](../../docs/design/m0-validation.md)，下述长期职责不等于已支持。

状态：长期职责基线；M0 有界读取子集已实现，其余推荐能力待验证。

分别适配湖表事务/快照、文件扫描、训练样本组织与外部 catalog。M0 先固定 Parquet manifest，M1 验证 Iceberg v2/Parquet 受限 Snapshot reader，M2 单表 writer 独立验收；REST Catalog 通过适配隔离具体服务。依赖与删除/schema 特性按当前切片白名单验证，不要求 writer 和全格式作为首个 reader 的前置。

外部湖和 AI 数据格式是持续扩展的兼容目标，当前没有已验证支持列表。外部 Lance、Delta 等数据保留原生事实来源；直接读取、导入、导出、原地写回分别声明，不要求先全部转成 Iceberg。

每个适配器声明格式/版本、schema/类型映射、投影/过滤下推、固定快照、删除、演进、增量、批量读取与写回能力；必需语义不支持时明确失败。读取文件成功不等于正确处理表快照、position/equality delete 或更新合并。

与 catalog 固定逐源版本及保留/pin 条件，与 query/DataFusion 协商扫描和残余过滤，通过 storage 进行对象读取。外部 catalog 的提交协议不自动等于 GuraDB read view 发布或跨源事务协议。

身份遵循[数据合同](../../docs/product/data-contracts.md)，无键源仅保证快照内身份。首条触发增量只认证 Iceberg 稳定键 append-only 历史链，其他变化明确拒绝或按配置 Snapshot 重建；源特性不被 reader 支持时，重建同样拒绝。

Lance 外部读取适配与 index 的内部向量物化是两种职责：前者遵循外部源所有权和原生版本，后者从固定事实版本构建可重建派生布局。原始媒体引用保留稳定对象身份、版本与坐标/模态信息。

凭证通过独立引用解析并限制作用域，不写入业务记录、查询结果或示例。源快照被外部 vacuum 或对象被覆盖时明确失败，不能静默换成最新版本。

新增适配器须提供官方格式样本、版本/读写方向、跨引擎验证、演进/删除测试及限制证据；先通过只读或导入验收，再开放写回。

设计依据：[技术架构](../../docs/architecture.md)、[产品功能架构](../../docs/product/functional-architecture.md)、[检索与 Graph 调研](../../docs/research/search-and-graph.md)、[兼容矩阵](../../docs/compatibility/lake-formats.md)。
