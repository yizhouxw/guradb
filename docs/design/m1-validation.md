# M1 验收映射与证据

本页描述实际driver范围，最终是否通过以当前commit/checkout绑定的harness报告为准。组件通过不等于完整P0/生产发布。

| 部分 | 真值/行为与负例 | 实际入口 |
| --- | --- | --- |
| Iceberg固定Snapshot | PyIceberg独立writer/reader；显式历史快照；Parquet field ID/顺序/类型；v1、演进、分区、position/equality delete、重复文件/键、NULL键、跨根、缺失/损坏/大小和预算拒绝；真实S3读取 | tests/functional/m1.py、scripts/m1lib/negative.py、tests/faults/component/m1.py |
| 身份与媒体/特征 | v1键编码、全量唯一性、特征覆盖一一对应、模型/维度/有限数值、媒体实际hash读取及受控副本下载；HTTP int8十进制字符串 | 同上功能driver |
| PG目录与发布 | operation幂等/输入冲突、ready不提前发布、单路索引失败旧视图、generation晚完成、CAS冲突、事务中断、响应丢失对账、PG重启 | tests/faults/component/m1.py |
| 检索质量 | 独立穷举L2、全文词项命中/同分键排序、单路排序推导RRF、过滤在候选窗口前、无效model/维度/请求预算拒绝 | tests/functional/m1.py |
| HTTP与CLI | 真进程/真实HTTP查询及CLI退出输出、同一view上下文、历史显式view、发布后已接受结果不变、跨主体隐藏、撤权后status/results/Parquet/media拒绝 | tests/functional/m1.py |
| 训练 | PyArrow读取实际导出Parquet、与manifest样本/模态/版本完全核对；独立SHA split算法；固定seed重复导出 | tests/functional/m1.py |
| pin/GC与恢复 | pin/retiring竞争、当前引用拒绝、只清旧物化不改源；排队/运行取消、执行期撤权、真服务进程kill后的worker_restarted/释放pin、PG重启 | tests/faults/component/m1.py |
| 组件成本 | 固定8192行/2文件/2维、真实构建GET/bytes精确核对；5次cold-process/warm-process延迟/RSS、artifact读取成本；同负载后台重建与检索/训练并测、精确top10真值；预定60秒构建/10秒查询/512MiB RSS预算 | tests/performance/component/m1.py |
| 契约与工程 | OpenAPI标准及正反例、Python实际AST归属/import DAG/循环与外部依赖、锁安装/compileall、已有M0回归 | contracts/harness suites 与 harness check |

直接执行 `scripts/m1_acceptance.py` 生成result.json/trace/服务日志；harness将三个M1 driver与原M0 driver纳入对应suite。每个切片保留失败现场，不把中途成功摘要当最终代码证据。M1新增Python流程不是Rust门禁的覆盖范围；编译/AST与依赖检查另行执行。

外部保留在构建成功前仍依赖上游对象存在；构建后所选闭包有受控副本。无源writer提交fencing、增量/ANN/Graph、真实多节点、元数据库HA/恢复SLO、恶意文件沙箱、多语言分析器或整库长稳证据。远端Actions未运行新代码，本地通过不能称远端通过。完整performance/stability/soak保持planned。
