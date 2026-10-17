# M1 完整有界闭环：Snapshot、持久发布、检索与训练

状态：实现与单独复核完成，最终提交后门禁/归档由task-finish收口。Git 原始基点 `0e216895db06edf36dcdb91e540a80a3869d0bd9`，工作分支 `codex/m1-foundations`，独立 worktree `/Users/chad/dev/guradb-m1-foundations`；开始时干净，恢复点见 task-status。

## 用户可观察验收与范围

用户明确选择完成整个M1闭环，本任务从两个基础组件扩大为完整有界M1；保留原始base和task ID，不新建任务掩盖范围。沿路线图依次完成：

1. 操作者显式提供 Iceberg v2 metadata 位置、SHA-256 和 snapshot ID，在受控 local 或已认证 S3 根内解析 Avro manifest list/manifest，完整校验特性后转为 M0 可读取的不可变 Parquet manifest。由独立 PyIceberg writer/reader 与现有 HTTP 结果核对。
2. 小型 PG18 目录持久保存数据集、Snapshot 定义/运行、revision/read view、发布 epoch 和 pin；用事务/CAS 与 generation fencing 验证旧任务晚完成、并发发布、响应丢失对账、失败/重启后旧完整视图。提供操作者命令入口和固定发布物导出，HTTP 沿用 M0 的受控启动配置、授权与固定视图，无热刷新。

白名单：非空、非分区、单一 schema/spec、无排序演进、平面 long/string/boolean、Parquet、仅 data manifest、snapshot 内文件有界。拒绝 v1/v3、删除 manifest/条目、schema/分区演进、嵌套/未支持类型、缺失/损坏/跨根对象、重复文件及超限；不以文件扫描替代删除语义。支持历史 snapshot，但 snapshot 的 schema 必须等于唯一 schema。无外部源写入、无源 GC、无增量和REST Catalog；源是唯一写入权威。M1所选依赖闭包使用managed-copy；兼容M0 manifest仍保留其v1 best-effort字段。

3. Tantivy BM25、精确平方L2与RRF固定分析器/model/候选窗口，完整特征覆盖；HTTP/薄CLI同视图扫描/检索与受控媒体下载。
4. 同视图训练manifest、独立SHA确定性split、Parquet导出，训练pin、撤权、GC和重启故障；Python依赖/进程边界以ADR0011固定。

## 风险与不变量

涉及 connectors/storage/catalog/common 与真实 driver/harness。INV-001/002/003/004/005/006/008/010/011：源版本、SHA 与读取绑定；两阶段构建/发布；事务发布 fencing；失败保留旧视图；pin/retiring 的排他序；无隐式 LIST/源修改。PG不存逐行业务数据。新增 Python 生产模块纳入唯一归属与真实 AST import DAG 检查。

## 最小切片、预算与故障断言

A：冻结源/输出合同，实现有界元数据读取与负例，实际 HTTP 互操作；单对象32MiB、元数据4MiB、合计扫描32MiB、最多32个文件、64字段、元数据记录最多4096，文件解码沿用M0预算。快照构建测量输入GET/字节、耗时、RSS；固定8192行smoke，60秒/512MiB为组件预算，不是产品SLO。

B：版本1独立 PG schema，显式初始化，无既有PG迁移；构建先创建 generation，产物校验后 ready，publish 原子切指针；旧 generation/CAS冲突拒绝。幂等 run id 对账；发布事务中断不得部分可见；新连接/PG重启验证持久状态。pin 与 retiring 在同一数据集行锁下操作，存在 pin 不能 retiring，retiring 不能新 pin；不执行对象删除。

PG部署需备份；无自动降级/删除schema。代码回退不撤销已提交目录状态，保留schema与产物后核对。失败日志、trace 放 artifacts；没有两次无新证据的盲重试。PG权限为操作者入口，HTTP继续M0每次请求/执行点授权，不把离线目录快照称为在线权限服务。

## 验证合同与完成

每组件独立真值/负例、固定负载成本与真实故障；既有M0四项运行时门禁全部回归。新门禁通过policy加入，CI安装固定锁。最后单独复核、有限切片提交、原base提交后check、task-finish建立checkpoint并归档；报告明确M1整体/完整performance/stability/soak未完成。

已有局部功能、组件性能和故障验证；中途发现Iceberg文件顺序不稳定、Docker随机端口重启变化，均保留现场并修正。独立复核补齐完整依赖副本、受控媒体下载、pin命名空间、失效lease/终态fencing及int8输出。首轮整项9类门禁通过；[复核](../reviews/2026-10-17-m1-implementation.md)后修正公共上下文、排队deadline和release事务顺序，最终commit/checkout digest/checkpoint以task-finish归档报告为准，不以此文自证通过。

恢复：首次pre-commit发现Git环境泄漏，失败现场完整留在原worktree；原main未变，已按流程abandon原任务并recover原checkpoint到 `/Users/chad/dev/guradb-m1-recovered`，分支 `codex/m1-complete`，新task checkpoint `checkpoints/20261017T104232Z-before-m1-complete-e56d4276`。原始base仍为0e21689，全M1范围不缩小；追加runner隔离与真实worktree hook回归。
