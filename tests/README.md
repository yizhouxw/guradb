# 测试与验收规划

当前有仓库/policy 检查、`tests/contracts` 的标准 OpenAPI/语义契约，以及 `tests/harness` 的执行/架构/性能比较/故障证据自测，M0 已接入真实HTTP/Parquet/S3/PG18、组件性能和故障driver，见[验收映射](../docs/design/m0-validation.md)。运行入口见 [harness](../harness/README.md)，不要把这些测试称为数据库能力验证。

开发工具测试还覆盖真实 Git checkpoint/恢复、任务 base 与 worktree 状态、完成证据重算/日志摘要和归档、GitHub Actions 范围/权限/总预算；本地 CI 配置检查不证明远端 job、分支保护或部署已经运行。

| 层次 | 要验证的行为 |
| --- | --- |
| 查询正确性 | SQL 子集、空值/类型、参数、过滤、排序、全文、精确向量、图遍历及组合结果 |
| PostgreSQL 兼容 | PG18 固定子集的 SQL/类型/函数差异；拒绝未支持事务/约束；wire protocol 单独验证 |
| 格式互操作 | 指定格式与版本的读/写、删除、快照、schema 演进和不支持特性拒绝 |
| 一致性与恢复 | data revision/read view、默认 published 与显式最新读取、提交结果未知、旧构建晚完成、源/发布双层 fencing、崩溃与安全回收 |
| 接口与权限 | SQL/HTTP/CLI/MCP 语义一致、越权、只读绕过、预算、游标、取消与重试 |
| 分布式故障 | 多节点退出、网络分区、重复任务、元数据切换、分片迁移与扩缩容 |
| 检索质量 | 在固定数据集上与精确结果/人工相关性基线比较，记录过滤条件和召回误差 |
| 性能 | 训练吞吐与在线延迟/吞吐并测，附规模、并发、冷热缓存、硬件与成本 |

每项兼容性声明必须链接到可复现测试及已知限制。真实格式测试优先使用规范和官方工具产生的样本；性能结果不作为缺乏正确性与故障验证的替代。

各切片实验及退出条件见[路线图](../docs/roadmap.md)。本项目不以业务 OLTP TPS 或实时事务延迟作为验收目标；保留批量写入正确性、并发检索、训练吞吐、冷热成本、相关性和恢复门槛。

M0 rust/functional/performance-smoke/stability-component 为ready，完整performance/stability/soak仍planned；相应missing门禁会阻止发布通过。将其改为 ready 时须接入真实 driver/断言，见 [首次内核接入](../harness/runtime-onboarding.md)。测试中的合成数值、临时 Cargo 包和 trace 仅为 harness 负向用例，不是产品 benchmark、故障模拟器或生产基线。

普通运行时变更要求功能与适用语言检查，加真实组件性能/稳定性；组件 driver 使用 `tests/performance/component/`、`benchmarks/component/`、`tests/faults/component/`。完整 driver 变更继续触发完整套件；发布要求完整基准、fault registry 与 soak，不能把组件通过解释为整体产品已通过。
