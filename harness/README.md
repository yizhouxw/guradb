# GuraDB Agent Harness

**2026-10-28现行阶段策略：** 先按[核心链路优先验收](validation-strategy.md)验证用户用例、资源模型与数据流；全面覆盖/回归/性能长稳分阶段推进。本页旧全面前置条款仅描述现有执行器或后续强化/发布义务，不再定义前期产品优先级。机器选择器尚未适配，不能把文档决定冒称工具已生效或绕过hook。产品/Actions继续暂停。

这是仓库内的工程质量控制入口，面向 agent 与人共同维护的长期代码库。它把工作流程、架构边界、质量门禁和执行证据连接起来；不是数据库实现，也不是自动证明正确性的系统。

## 立即使用

需要 Python 3.11+、可用Git和Docker。Python承载harness与验收，Rust使用固定容器工具链，见[M0运行说明](../docs/design/m0-running.md)。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock -r requirements-m0.lock -r requirements-m1.lock
.venv/bin/python scripts/harness.py install-git-hooks
.venv/bin/python scripts/harness.py plan
.venv/bin/python scripts/harness.py check
```

`check` 默认按实际变更运行。本地 active task 使用其原始 base；没有任务时与 HEAD 比较，包含 staged、unstaged、untracked、删除和重命名两端。`--base <ref>` 按 merge-base 计算，`--base all` 检查整树；CI 自动读取 PR base 或 push before，手动运行默认全树。无法解析基线时失败，不把变更当空集。

可用 make 时 `make setup`、`make plan`、`make check` 提供同样入口；本机 make 受 Xcode 许可限制时直接使用上述 Python 命令。

```sh
# 只检查 harness/仓库/契约，不证明数据库质量
.venv/bin/python scripts/harness.py check --scope bootstrap
# 对拟议路径做风险计划，不创建该文件，也不执行门禁
.venv/bin/python scripts/harness.py plan --path modules/storage/src/cache.rs
# 运行所有发布门禁；当前完整performance/stability/soak缺失，预期失败
.venv/bin/python scripts/harness.py check --scope release
```

离线首先从[PM START](pm/START.md)读取[当前索引](pm/START.md)、[本地任务](tasks/README.md)与[成员记忆](members/README.md)。session仅执行实例，PM全项目唯一会话，GitHub Issue可选；[ADR0026](../docs/decisions/0026-goal-driven-collaboration.md)明确五角色与按需领域知识，不改变harness执行行为。

团队职责、技术升级与派发规则统一见[团队协作规范](team-collaboration.md)，模块标签见[清单](module-labels.json)。PM亲自负责组织、协作制度与记忆治理；开发负责人自主完成技术目标包，调度提示只引用恢复入口。当前[暂停远端Actions/PR CI准入](ci-cd.md)，本机适用自测、独审和精确main核验继续必需。

并行开发统一按 [GitHub PR 流程](parallel-development.md)：一任务一分支/worktree，独立证据与审查，依赖顺序串行合入 main；2026-10-26直接main治理例外仅属历史任务；本次及后续治理仍走普通分支/PR，保留正常hook和本地验证。

## 工作闭环

1. 阅读根和受影响模块的 AGENTS、对应 ADR、接口与最近失败证据；只加载相关上下文。
2. 运行 `plan`，列出变更触及的不变量、功能基线、性能风险和故障边界。
3. 对跨模块、持久数据、发布/GC 或热点改动使用[变更计划模板](templates/change-plan.md)；小型文档修订无需填表。
4. 先更新[用户手册](../docs/user/README.md)合同与[场景验证表](templates/user-scenario.md)，再实现一个可审查切片，先保留最小复现/结果基线，再修改行为。不捎带无关重构。
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
| [Git 追溯与恢复](version-control.md) | 有限切片提交、检查点、提交前门禁与保留现场的恢复 |
| [开发流程](development-workflow.md) | 任务起止、验收/复核、失败与交接、依赖/迁移及证据归档 |
| [团队协作](team-collaboration.md) | 五活跃角色、目标包自主交付、模块领域知识、最少沟通与上下文 |
| [本机质量与 CI 暂停](ci-cd.md) | 当前本地验收、Actions停用状态与重新启用条件 |

本地依赖检查含 Cargo 普通、dev、build、target-specific 和 workspace 继承，以及包/模块循环。未归属代码、超过 600 行的源文件、检查范围内的符号链接会失败。600 行是可维护性门槛，不是性能指标；Python生产模块另做真实AST import DAG、compileall与锁/依赖检查；其它新语言仍需对应检查器，不能只靠Cargo lint。

## 现在能证明什么

当前可执行：仓库检查、OpenAPI 标准/语义契约、policy/架构检查、harness 自测、性能比较器和稳定性证据校验器。新增unit-coverage纳入全部Python/Rust生产源，现行要求Python全部自研生产源至少80%、Rust原适用源100%覆盖，Rust有限排除按[清单](coverage-exclusions.json)绑定源码并单列原始数值，未豁免缺口使门禁失败；工具ready不表示当前代码已经达标，见[测试入口](../tests/README.md)。

M0/M1 已接入真实功能、组件基准和故障注入；完整性能、完整fault registry、长稳/升级在 policy 中仍为 `planned`。涉及运行时的变更要求相应 suite；未接入时返回 `missing` 并失败，不跳过成绿。`release` 当前也必须失败。

普通服务端变更要求功能、适用语言检查、`performance-smoke` 与 `stability-component`，先验证当前可运行切片。完整 driver 变更仍要求对应整库套件，`release` 包含完整性能/fault registry/soak。分层不会把缺失的运行时测试显示为通过，也不要求首个扫描组件先实现完整分布式数据库，依据 [ADR 0007](../docs/decisions/0007-incremental-delivery-and-gates.md)。

每次检查生成独立的 `artifacts/harness/<run>/report.json` 和命令日志，包含 commit、工作区指纹、选择依据、状态与耗时。超时/工具缺失/退出非零/超量日志分别记录；POSIX 下清理整个子进程组；检查期间源文件变化使结果失效。

非小型任务用 task-start 记录目标与原始 base，task-status 恢复上下文，最终提交后 check，再用 task-finish --report/--review 验证整项范围并归档；task-abandon 只停止记录，保留文件与 Git 历史。checkpoint 同样重验报告/全部命令/日志 SHA-256，证据归档到共同 Git 管理目录，不依赖 artifacts 永久留存。

GitHub Actions质量和诊断工作流当前已按用户指令停用，配置保留；PR不再等待远端quality检查。历史失败/缺失原样记录，本机适用检查、独审与main证据仍须真实通过；完整release的planned/missing仍阻断。未来恢复CI/CD与平台required checks须重新讨论授权，见[当前规则](ci-cd.md)。

## 模块交付 v2 的本地入口

[策略v2](../docs/plans/2026-10-21-modular-delivery-v2.md)、[需求矩阵](../docs/product/requirements-v2.md)及[模块合同](../docs/design/module-delivery-contracts.md)保留。机器接线使用module/pair/system/release分层，完整owner生产源分母、Python80%/Rust100%、真实依赖、原预算/负例/恢复/追溯不变；未知映射扩大为system，工程工具自测不冒充产品验收。CI当前暂停，不改变本地层级与release missing。

## 2026-10-24 用户授权的现行覆盖阈值（Refs #23）

Python 全部自研生产源行覆盖率至少80%；Rust仍为现有经审查排除后的适用行100%。两者用合法整数covered/total交叉相乘判断，total必须大于0，不用显示百分比或舍入。完整源分母、未导入文件、身份前后绑定、测试失败拒绝保持；Python仍不允许行排除，Rust原21行清单不扩大。旧100%要求/历史报告保留为当时合同，不改写原失败或测量。本次政策实现与边界验证另记；80%不等于完整产品验收。
