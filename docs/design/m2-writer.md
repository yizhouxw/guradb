# M2-W 托管 append：白名单与验收计划

仅可信操作者入口管理本机 file:// 仓库，PyIceberg 0.10.0 SQL/SQLite catalog；业务 worker 无 catalog/warehouse 提交接口。固定字段 `id: required int64, title: optional string, active: optional bool`，id 为整个表生命周期唯一键。单批 1–1000 行、表累计至多 10000 行、32 次已提交批次（与当前 reader 的 32 文件上限一致）；纯 append，拒绝覆盖、删除、schema/分区演进与外部写入。非生产 HA，不承诺恶意同 OS 用户隔离。

独立 PG managed schema 保存配置、generation、operation/input 指纹、parent、状态及已确认 snapshot；不修改 M1 目录。准备新意图提升 generation，旧意图不得提交。所有提交者必须经过本机同一受控入口，持有仓库 flock 串行锁；锁贯穿源提交和 PG 记账，PG 连接丢失也不能让另一提交者越过仍持锁的旧进程。目录 read-view CAS 不参与源 fencing。进程死亡由 OS 释放 flock，恢复先按 operation/fingerprint/parent 在 Iceberg snapshot summary 对账；缺失且 parent 未变才可重做，父版本变化或多个匹配均明确失败。已提交操作重复返回同一 snapshot，不能盲目再 append。

验收：真实 PG +真实 Parquet/Iceberg；独立 catalog reader 核对全部行；重复及冲突 operation、跨批重复键、固定 schema/变更拒绝、旧 generation、并发、源提交前和后崩溃窗口、响应丢失后新实例恢复。注入只在明确边界触发，不伪造成功。源提交与检索发布分离，调用者后续运行 Snapshot 构建与发布。生产许可、远端仓库、HA、容量和长稳仍缺证据。

未提交意图仅在完整 parent 链且 HEAD 仍等于已持久 parent、受控 flock 排除了运行中提交时可认定未提交；新 operation 将其标记 aborted，旧 operation 此后明确拒绝。任何无法对账结果均阻断新提交。已确认结果保留原 metadata URI、SHA-256 与 snapshot，不因后续 append 漂移。历史截断、分支或旁路回滚均拒绝。

实际验证入口：`.venv/bin/python tests/functional/writer.py --run-dir artifacts/writer-<run>`（真实 Docker PG、独立 PyIceberg reader、进程死亡）；契约入口 `.venv/bin/python -m unittest discover -s tests/contracts -p test_writer.py`。这些是组件证据，不能替代性能/完整故障/soak/release。

累计输入 JSON 至多 8 MiB、Arrow decoded 至多 16 MiB，现有 Parquet 文件至多 12 MiB 后才允许下一批（单批输入至多 2 MiB，给压缩/metadata 开销留余量）；跨批超限在源提交前拒绝。这个保守组件预算用于保持 M1 有界读取路径可用，不替代后续 features/发布预算验证。对账方法是私有 locked helper，只由持 flock 的提交入口调用。
