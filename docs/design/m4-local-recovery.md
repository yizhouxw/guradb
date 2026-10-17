# M4 本地联合备份恢复切片

## 变更计划与验收

范围：停服并冻结外部写入的本地 M1/M2 managed-copy 已发布视图、训练 pin、结果对象和 PG 控制面。备份锁定控制表以阻止并发元数据写入，复制完整显式托管根；不通过 LIST 推断湖快照。恢复必须使用新目录和没有 Gura schema 的独立 PG 数据库，禁止覆盖原系统。

用户可观察验收：备份摘要校验成功；恢复的 published view、训练 pin、查询和训练结果保持同一逻辑版本；权限撤销仍然生效；缓存由新服务实例重建。损坏、symlink、越界引用、不兼容版本、活动任务和未对账托管 writer 状态均失败闭锁。

不变量：目录和不可变依赖闭包共同恢复；恢复完成前 PG 不出现半导入；每个本地引用限定到显式根；源 URI 作为身份保留而非恢复时重新获取。当前支持停服本地演练，不支持在线备份、PG HA、跨机 DR、S3 联合备份。外部写入冻结由运维负责，PG 锁不能冻结文件系统写入。

最小实现：版本化 JSON 控制面导出 + 每文件 SHA-256 + 托管 writer flock，使用现有 schema.sql 类型约束导入；本地产物 JSON 引用搬迁并递归重算引用摘要，原 revision/view 和源版本不变；训练 Parquet 二进制不改写。缓存不属于备份权威来源。托管 writer 源必须位于同一显式备份根的独立严格子目录，多个源目录不可嵌套；冻结后复制 SQLite catalog 与 Iceberg warehouse，恢复时专门改写 SQLite metadata URI、Iceberg JSON URI、Avro manifest/list URI 和 manifest_length，再更新 PG intent metadata 摘要。prepared/committing 状态拒绝备份，须先对账。

功能真值：真实 PostgreSQL 导出/导入后逐项对比目录、pin、产物字节与授权行为；负例修改备份对象验证拒绝。性能预算为本地有界总文件 4096、总字节 512 MiB、单文件 64 MiB，失败保留现场；无性能提升声称。故障断言：备份无 COMPLETE.json 不可恢复；导入失败事务回滚，残留新目录保留供检查且不自动覆盖/重试。


## 操作入口与恢复纪律

DSN 仅从环境变量读取，输出不包含连接串。必须停止服务、构建、训练和所有外部 writer；`--writes-frozen` 是运维声明，不能取代冻结。程序额外检测服务 advisory lease、目录表 SHARE 锁和每个托管源 `.committer.lock`，冲突即拒绝。

```sh
.venv/bin/python scripts/m4.py backup --root /absolute/state --destination /absolute/backup --writes-frozen
.venv/bin/python scripts/m4.py verify --backup /absolute/backup
# GURADB_PG_DSN 在此应指向新建的独立空数据库，不能指向原系统。
.venv/bin/python scripts/m4.py restore --backup /absolute/backup --destination /absolute/restored
```

原系统与备份必须保留至恢复演练通过。备份目录必须是新路径且不能嵌套在源根；恢复目录也必须新建，PG 中存在任何 gura_m1/gura_managed schema 均拒绝。没有 COMPLETE.json 的目录不是有效备份。失败目录保留供诊断，不能自动覆盖重试。元数据导入在 PG 单事务内完成；文件系统没有跨 PG 原子提交，崩溃可能遗留新目录，需检查该新目录和新数据库后人工重建独立目标。

恢复改变物理路径和有关产物摘要，保留逻辑 run/view/revision/source_versions。已经发布的 managed-copy 查询与训练结果无需原湖；外部 dataset 的定义仍指向原外部 URI，恢复不承诺继续刷新不可用外部源。托管源 URI 搬迁不等同于新的业务数据版本。对恢复后增量刷新仍须重新验证源历史合同，不能据此声称普适增量迁移支持。

备份有完整性摘要而没有签名/加密；只接受运维持有的可信备份，不提供恶意备份认证或跨租户导入。备份包含 token 摘要与权限表，按敏感运维资料管理。恢复权限为备份时点状态；备份后发生的撤权必须在开放新系统前重新应用。演练覆盖备份前已撤权以及恢复后新撤权，不宣称可以从旧备份自动推导新撤权。

## 实际验证

独立 driver：`tests/functional/m4.py`。真实 PostgreSQL 容器 + PyIceberg 本地源 + Tantivy 产物：发布视图、训练导出及 job pin、恢复后删除原数据树/外部湖、检索真值、训练 Parquet、权限撤销、managed operation 幂等对账与新 append。负例含服务未停、未声明冻结、目标数据库非空、摘要损坏、越界路径、symlink 和版本不兼容。命令与报告由主任务最终报告绑定当前代码指纹；这里不复用旧运行的通过结论。
