# 测试与验收规划

当前有仓库/policy 检查、`tests/contracts` 的标准 OpenAPI/语义契约，以及 `tests/harness` 的执行/架构/性能比较/故障证据自测，M0 已接入真实HTTP/Parquet/S3/PG18、组件性能和故障driver，见[验收映射](../docs/design/m0-validation.md)。运行入口见 [harness](../harness/README.md)。仓库/契约/harness自测只证明工程设施；真实数据库driver仅证明其明确白名单。

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

## 单元测试覆盖率与双接口场景

覆盖率入口（锁定 coverage.py 7.11.0、Rust 1.90.0/LLVM 和 cargo-llvm-cov 0.6.21）：

```sh
.venv/bin/python scripts/unit_coverage.py --language all --run-dir artifacts/unit-coverage-new
```

目录必须是新的。Python运行`tests/unit`及现有`tests/contracts`，只统计`modules/`、`clients/`全部32个生产文件，包含namespace目录和未导入文件，不启用任何行排除。进程/HTTP场景driver不合并到该结果。现有contract测试含真实索引与进程边界检查，因此这是单元/组件契约测试集合，不能把它称为纯隔离单元测试覆盖率。Rust运行workspace单元测试，以`crates/*/src/**/*.rs`全部生产文件为分母，单元代码位于`crates/*/tests/unit/`及共享fixture。Rust门禁按LCOV DA的唯一可执行源码行统计，保留LLVM原生汇总（含嵌套函数/闭包映射），两者分母不同；按未豁免缺行整数判断100%，不使用显示百分比四舍五入。

[排除清单](../harness/coverage-exclusions.json)仅对难以合理覆盖的Rust防御/平台边界及LLVM映射闭合符逐行豁免。记录类别、原因、替代证据、文件SHA-256和每行原文；无glob或行范围，源码变化必须重新审查。可测错误路径仍补测试，不批量排除入口、网络、授权、预算或取消逻辑。当前Python无排除。

输出包括Python JSON/HTML、原始Rust LLVM JSON/LCOV、`rust-summary.json`逐文件原始/排除/适用行和缺口，以及代码身份/工具版本/测试结果。原始覆盖率不改写；100%明确指排除后适用源码行。缺工具/源文件缺失/测试失败/任何未豁免缺行或失效清单都失败；尚未达标不标已完成。harness/验收脚本为开发工具，继续由`tests/harness`单独验证，不混入数据库生产代码分母。行覆盖不能替代分支覆盖、独立真值、故障注入或检索质量。

同一checkout的覆盖率运行使用排他锁；并发请求明确失败，避免cargo-llvm-cov清理/合并共享target时混入另一轮计数。失败或退出释放锁；确认前一轮结束后使用新的run目录重试，不删除锁文件抢占活动测量。

[共用场景](functional/interface_scenarios.py)在M0 functional的PG子driver中启动真实HTTP及PG监听，对同一不可变manifest执行15种查询、7种参数场景、17种拒绝及撤权/恢复；每个成功场景同时比对HTTP、Psycopg 3.2.10 text/binary结果和PG18真值。int8按接口合同归一化，bool不当整数。保留原有psql、PG raw协议、容量/取消/预算、HTTP分页与S3测试。

M1/M2的scan/search/graph/export仍由现有HTTP/CLI/MCPdriver验证；PG SQL端口只覆盖M0白名单，不声称这些job也有SQL入口。最新数值、缺口和命令见[实现与测试复审](../docs/reviews/2026-10-18-implementation-and-tests.md)。

## 2026-10-24 用户授权的现行覆盖阈值（Refs #23）

Python 全部自研生产源行覆盖率至少80%；Rust仍为现有经审查排除后的适用行100%。两者用合法整数covered/total交叉相乘判断，total必须大于0，不用显示百分比或舍入。完整源分母、未导入文件、身份前后绑定、测试失败拒绝保持；Python仍不允许行排除，Rust原21行清单不扩大。旧100%要求/历史报告保留为当时合同，不改写原失败或测量。本次政策实现与边界验证另记；80%不等于完整产品验收。
