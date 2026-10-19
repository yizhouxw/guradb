# Catalog

M0 当前实现见对应 `crates/guradb-catalog`，仅限[有界读取设计](../../docs/design/m0-parquet-http.md)与[实际验收映射](../../docs/design/m0-validation.md)，下述长期职责不等于已支持。

状态：M0 固定manifest目录及M1/M2有界PG控制面已实现，包括generation/epoch发布、授权、job/pin、源提交意图和离线联合恢复；范围见[目录实现](control.py)、[恢复](recovery.py)及[M2操作](../../docs/design/m2-running.md)。下文为长期职责，通用catalog、HA/PITR和历史生命周期仍待实现/验收。

推荐 PostgreSQL 作为强一致的小型控制元数据库，保存资源/schema、权限、作业/租约、版本引用、发布指针与恢复状态；不存放业务逐行数据、所有候选或逐条图边。

负责 data revision、index artifact manifest 与 read view 的身份、引用和原子发布，区分 `data_committed` 与 `search_ready`。大清单保存在对象存储，控制面保存稳定引用与小规模状态。

对查询提供固定版本视图，默认选择已发布 read view；跨外部源只能保证所披露的逐源版本集合，不能将其称为统一原子时点。权限撤销独立生效，不等待旧视图或索引重建。

Iceberg REST Catalog 通过 connectors 的适配接口接入；源格式提交、GuraDB 指针发布与外部 catalog 提交分别设计。GuraDB 读者的原子发布不等于所有外部引擎同时看到多表变化。

发布使用预期旧版本、作业身份和 fencing/CAS；提交结果未知时先对账。维护查询/训练 pin 与保留引用，为 storage 回收提供依据。PostgreSQL HA、备份与恢复需要演练，不能因选用元数据库便视为已具备高可用。

POC 验收并发发布冲突、失权 worker、崩溃/未知提交恢复、权限撤销、源快照过期与回收安全。

设计依据：[技术架构](../../docs/architecture.md)、[产品功能架构](../../docs/product/functional-architecture.md)、[检索与 Graph 调研](../../docs/research/search-and-graph.md)、[格式兼容](../../docs/compatibility/lake-formats.md)。
