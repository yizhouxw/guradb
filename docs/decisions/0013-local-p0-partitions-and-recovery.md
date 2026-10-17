# ADR 0013：本地 P0 分片、记录版本与恢复

- 状态：有界实现；本次 commit 报告决定通过的门禁，不代表生产发布
- 日期：2026-10-17
- 关联：ADR 0004/0006/0007/0011/0012；[变更计划](../design/local-p0-change-plan.md)

## 决定

append-only refresh 校验完整历史及旧文件身份，只从源读取新增 data files。旧行、物化文件与依赖从校验后的副本复制到新 run，旧逻辑记录继承版本。旧特征、模型或媒体变更拒绝。索引仍完整重建；不称索引增量。文件 stat/S3 HEAD 是可信上游不可变身份检查，不是对恶意同身份改写的密码学证明。旧 bundle 缺 identity 时先显式 Snapshot 建立新基点。

新 Snapshot 持久生成三个按逻辑键轮转的 serving Parquet；查询与训练 worker 仅读本片，返回 PID、实际行数、RSS 和成本。ANN 为每片独立 Lance IVF_FLAT；不足每 partition 16 行的小片明确报告 exact-small-shard。全局候选合并后再做 Top-K/RRF；每个分片都接受原始候选窗口，不减少召回预算。

Tantivy Python 绑定不能注入全局统计。新视图使用 `bm25-global-v2`：ASCII 字母数字、小写、OR token，k1=1.2、b=0.75、精确词频/长度和全库 df、float64 BM25。三份物理 postings 使用同一不可变全局统计，过滤在统计之后。与 Tantivy fieldnorm/f32 分数可能有细微差异，因此 context 中索引 ID 显式版本化。新构建使用bundle version 2，旧程序version 1 reader明确拒绝，避免默默换用旧评分。新程序读取旧bundle继续旧Tantivy路径。新实现同时保留旧索引产物供对照，存储开销计入实际构建成本，不声称已经优化。

总 deadline 和剩余读取/产物预算在三个任务之间预分配，完成时汇总真实计数；分配偏斜可能保守拒绝，不能超支再返回成功。IPC 以有界临时文件实现磁盘 exchange，队列与进程数有上限；没有通用 shuffle/spill 或跨机器调度承诺。

## 恢复与兼容

[离线联合恢复](../design/m4-local-recovery.md)先冻结服务与外部 writer，用 PG 锁及受控源 flock 保持目录/对象/pin 一致，恢复到新目录和空 PG 数据库。仅搬迁结构化引用，业务值保持。支持被测 PyIceberg SQL catalog/JSON/Avro 本地源搬迁；历史视图保留其 read context。恢复后首次源刷新使用显式全量 Snapshot，不能声称 operation/增量目标透明迁移。

权限是备份时点状态；开服前需补应用备份后的撤权。恢复不是 HA、PITR、异地 DR 或自动密钥轮换。旧版本服务回滚必须排空作业、保留被 pin 产物、选择旧索引版本视图；不能把代码回滚当作源数据回滚。

## 证据与缺口

独立公式验证 BM25、精确 L2/ANN 全 probe、全局 RRF、固定视图训练与 Graph。实际 PG 负载同时 append/refresh/publish、检索和训练；恢复演练删除原目录后读取、重试 writer 并追加。完整冷热/超过缓存、受控基线、长稳、生产 HA、多机容量和远端 CI 未获证据时继续阻断 release，见[生产缺口](../design/production-acceptance-gaps.md)。
