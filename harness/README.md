# GuraDB Agent Harness

这是仓库内的工程质量控制入口，面向 agent 与人共同维护的长期代码库。它把工作流程、架构边界、质量门禁和执行证据连接起来；不是数据库实现，也不是自动证明正确性的系统。

## 立即使用

需要 Python 3.11+ 和可用 Git。Python 只承载 harness 工具。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python scripts/harness.py plan
.venv/bin/python scripts/harness.py check
```

`check` 默认按实际变更运行。没有首个 commit 时检查全部文件；有历史时包含 staged、unstaged、untracked、删除和重命名的两端。`--base <ref>` 按 merge-base 计算；CI 自动读取 PR base 或 push before。无法解析基线时失败，不把变更当空集。

可用 make 时 `make setup`、`make plan`、`make check` 提供同样入口；本机 make 受 Xcode 许可限制时直接使用上述 Python 命令。

```sh
# 只检查 harness/仓库/契约，不证明数据库质量
.venv/bin/python scripts/harness.py check --scope bootstrap
# 对拟议路径做风险计划，不创建该文件，也不执行门禁
.venv/bin/python scripts/harness.py plan --path modules/storage/src/cache.rs
# 运行所有发布门禁；当前无内核，预期失败并列出缺失项
.venv/bin/python scripts/harness.py check --scope release
```

## 工作闭环

1. 阅读根和受影响模块的 AGENTS、对应 ADR、接口与最近失败证据；只加载相关上下文。
2. 运行 `plan`，列出变更触及的不变量、功能基线、性能风险和故障边界。
3. 对跨模块、持久数据、发布/GC 或热点改动使用[变更计划模板](templates/change-plan.md)；小型文档修订无需填表。
4. 实现一个可审查切片，先保留最小复现/结果基线，再修改行为。不捎带无关重构。
5. 运行 `check`；性能与稳定性命令必须来自真实 driver，证据固定到本次代码/数据/配置。
6. 单独复核差异、失败路径、资源复杂度和证据。高风险变更安排独立审查轮次或人工审查，不把作者的完成总结当作独立结论。
7. 汇报行为变化、执行的命令、报告路径、仍缺的证据与兼容/回滚影响；通过的是哪一层必须明确。

长任务中断/上下文恢复后，从当前计划、未解决风险、Git 状态和最新报告继续；旧摘要中的“已通过”不能替代代码指纹匹配的新证据。持久设计结论进入 ADR，不无限扩充根 AGENTS。

## 机器约束与文档

| 文件 | 职责 |
| --- | --- |
| [policy.toml](policy.toml) | ready/planned suites、命令、超时与代码规模上限 |
| [architecture.toml](architecture.toml) | 源文件归属、模块允许依赖与 Cargo DAG |
| [invariants.toml](invariants.toml) | GuraDB 关键正确性/稳定性义务；不是已验证覆盖 |
| [workloads.toml](workloads.toml) | 检索/训练/混合负载、必须同时观察的质量与成本指标 |
| [faults.toml](faults.toml) | 提交/发布/恢复/GC/撤权/取消的故障场景 |
| [质量模型](quality-model.md) | 风险分级、阶段门禁与复核要求 |
| [证据协议](evidence.md) | 性能比较、噪声、trace、种子和报告边界 |
| [首次内核接入](runtime-onboarding.md) | 从 planned 到真实代码门禁的步骤 |

本地依赖检查含 Cargo 普通、dev、build、target-specific 和 workspace 继承，以及包/模块循环。未归属代码、超过 600 行的源文件、检查范围内的符号链接会失败。600 行是可维护性门槛，不是性能指标；新增语言的真实 import 图仍需对应检查器，不能只靠 Cargo lint。

## 现在能证明什么

当前可执行：仓库检查、OpenAPI 标准/语义契约、policy/架构检查、harness 自测、性能比较器和稳定性证据校验器。

当前未实现：数据库功能测试、真实基准 driver、真实故障注入、长稳/升级。它们在 policy 中为 `planned`。涉及运行时的变更要求相应 suite；未接入时返回 `missing` 并失败，不跳过成绿。`release` 当前也必须失败。

普通服务端变更要求功能、适用语言检查、`performance-smoke` 与 `stability-component`，先验证当前可运行切片。完整 driver 变更仍要求对应整库套件，`release` 包含完整性能/fault registry/soak。分层不会把缺失的运行时测试显示为通过，也不要求首个扫描组件先实现完整分布式数据库，依据 [ADR 0007](../docs/decisions/0007-incremental-delivery-and-gates.md)。

每次检查生成独立的 `artifacts/harness/<run>/report.json` 和命令日志，包含 commit、工作区指纹、选择依据、状态与耗时。超时/工具缺失/退出非零/超量日志分别记录；POSIX 下清理整个子进程组；检查期间源文件变化使结果失效。

CI 在 PR/push 运行同一入口，并保留失败日志；共享 runner 不用于给数据库性能背书。当前无远端仓库规则配置，尚不能保证保护分支或阻止绕过 CI。建立远端后应将该 job 设为必需检查，并对 harness、基线和持久化协议变更设置独立复核；仓库内自检不替代平台合并权限。
