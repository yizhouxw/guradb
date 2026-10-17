# 首次运行时接入清单

当前没有 Rust workspace 或数据库进程，因此运行时 suites 为 planned。这是显式缺口，不是豁免。

## 第一个 crate / 客户端代码

1. 按[路线图](../docs/roadmap.md)只固定当前切片的 toolchain、依赖与 Cargo.lock；先验证 Arrow/DataFusion，不以尚未使用的 Lance/Graph/多节点为首 crate 前置。Python/其它客户端同样锁定自己的构建和依赖。
2. 在 [architecture.toml](architecture.toml) 选择逻辑归属；新位置/模块需要登记路径、允许边与验证职责，不使用任意目录逃避检查。
3. 将对应 [policy.toml](policy.toml) suite 的 state 改为 ready，提供实际 argv 命令和超时；ready 不能为空命令，planned 不能有隐藏命令。
4. Rust suite 至少执行 `cargo fmt --all -- --check`、`cargo clippy --workspace --all-targets --locked -- -D warnings` 与 `cargo test --workspace --locked`，并验证所用 feature 组合。是否使用全部 features 取决于互斥特性，不能盲目 all-features。
5. functional suite 注册真实行为、负例/差异/属性/集成测试，确保有非零执行数，不能用空的 discovery 或 harness 单测充数。
6. 服务端代码接入 `performance-smoke` 与 `stability-component`，执行当前组件的真实测量及失败/重试/取消或恢复测试。命令支持 `{python}`、`{run_dir}` 占位符，以独立目录存证。客户端至少执行功能与适用语言检查，实际热点风险仍要在计划中补充证据。
7. 为受影响不变量建立实现/测试映射，并在变更中说明尚未覆盖的义务；registry 里有名字不算覆盖。
8. 运行 `plan` 和 `check`，确认需要的门禁都运行且证据属于本次代码。缺失 driver 时保留失败，不将 planned 改成执行 `true` 的 ready。

组件 driver 放在 `tests/performance/component/`、`benchmarks/component/` 或 `tests/faults/component/`；这些路径触发对应组件门禁。父目录的其它 driver 仍触发完整性能/故障门禁。新组件测试也必须真的执行当前生产代码；不能以 stub、空发现、合成测量或总是成功的命令启用 ready。

CI 的实际结果 JSON、原始测量、trace 和恢复日志写入 `{run_dir}` 下的独立目录，确保上传步骤能捕获；外部 baseline/数据引用固定摘要和可取位置。发布前完整证据另存持久位置，本地 checkpoint 仅自动归档 harness 报告和命令日志，不代替 driver 产物归档。新增命令时核对 Actions job 总时限，必要时拆到受控 runner/job，不能让总时限小于所需串行门禁预算。

首次性能 smoke 先冻结输入、规模、缓存、重复次数、独立正确性真值，以及时间/内存/I/O 等适用绝对预算，再实际测量并保留原始数据。没有旧基线时记录 `baseline-established` 和未做回归比较的限制，不用 candidate 自比较。组件后续变更与经审查的同环境基线比较；复杂检索实现后注册真实 workload 并使用完整比较器。基线晋升不是测量命令自动批准的结果。

组件稳定性按实际风险覆盖失败传播、资源释放、取消或重启恢复，保留注入点、seed/步骤和断言日志。它不调用全库 `verify-stability` 冒充子集通过；该校验器始终要求完整 registry。尚未实现的全库场景列为缺口，在对应能力交付前补齐。此分层依据 [ADR 0007](../docs/decisions/0007-incremental-delivery-and-gates.md)，不是临时关闭某一质量维度。

## 从实验到发布

普通变更使用正确性、真实组件性能 smoke 和故障测试；高风险持久化/发布/热点变更在计划中增加涉及的集成/完整实验。完整 driver 变更自动要求对应完整门禁，完整基准在受控硬件复核；发布候选必须执行全部套件，包括完整性能、12 项 fault registry、长稳/升级及所声明格式矩阵。允许分层控制成本，不允许把未执行项显示为通过。

启用 soak 前应明确真实执行时长、混合负载、内存/句柄/SSD/队列趋势预算、重启/故障频率、恢复与升级/回滚断言。当前执行器单命令上限 3600 秒；更长实验用有界阶段/外部作业管理，保留任务句柄与最终证据，不能无限阻塞 agent。

远端仓库建立后，设置必需 CI 检查和独立复核责任。harness 和 policy 可以随仓库一起被修改，因此还需要合并权限/审查机制来阻止未经解释的门禁削弱，不能把自检当作不可篡改的信任根。
