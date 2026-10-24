# 开发流程：从任务到可验证交付

状态：本地任务与证据工具已接入；运行时范围见 [README](../README.md)，远端 CI 证据及待建立的 CD 合同见 [CI/CD 方案](ci-cd.md)。

## 1. 开始前确定什么

所有后续分配给成员的任务，先按[团队协作](team-collaboration.md)查重并建立独立GitHub Issue，补齐主模块/角色标签、assignee与唯一DRI、验收/文件域、依赖/关联PR、下一动作/检查时间；总协调单不能代替该任务。

普通需求先写可观察结果、非目标、所在里程碑、支持/拒绝白名单和验收案例；缺少规模/性能预算时先做有界测量，不能承诺尚无依据的 SLO。涉及跨模块、持久协议、公开接口、热点、基线或门禁，使用[变更计划](templates/change-plan.md)，关联 ADR/INV、功能真值、资源预算、故障断言及恢复边界。小型文字修订只需提交说明，不强制立项文档。

开始时读取 AGENTS/相关模块、Git 状态和最近失败，检查依赖锁与身份/hook；新环境按 README/setup 安装。已有用户改动先保留并辨明归属，不自动暂存、藏起或覆盖。所有任务默认使用独立分支/worktree，经 GitHub PR 合入 `main`；本次团队/harness治理任务经用户明确授权直接main提交，由唯一集成者协调串行窗口；并行范围、依赖和合入条件见 [PR 并行流程](parallel-development.md)，追溯与恢复见 [Git 工作流](version-control.md)。非小型实现启动任务：

```sh
.venv/bin/python scripts/harness.py task-start \
  --label bounded-task --objective '填写本次用户可观察目标'
.venv/bin/python scripts/harness.py task-status
.venv/bin/python scripts/harness.py plan
```

启动要求干净的已提交分支，记录 objective、原始 base、分支、checkpoint 和 worktree；已有 active 任务不能覆盖。状态位于各 worktree 自己的 Git 管理目录，历史 receipt 保留；不同 worktree 不共用 active 状态。plan/check/pre-commit 在无显式 base、无 CI 事件时自动使用 active task 的原始基点，因此多次提交后不会丢掉前面切片。切换分支或使原始基点不再为祖先时拒绝自动继续，先核对状态，不自动重写 base。

## 2. 实现与依赖纪律

用户可见变更必须先更新 [用户手册](../docs/user/README.md) 的场景合同，再修改行为代码，最后按文档验证。文档先写前置、命令/API、结果、支持/拒绝、权限/预算、兼容/迁移/恢复，新部分标待实现；用[场景表](templates/user-scenario.md)关联真值、正负例与报告。先行提交或实现前 diff/任务记录用于复核时序；文档可与实现同一最终提交。纯内部变更解释无用户行为影响，纯文字修订可轻量检查，详见 [ADR 0016](../docs/decisions/0016-user-documentation-first.md)。

先保留失败复现或独立真值，再实现最小切片。新增行为、缺陷修复与重构分别说明，不捎带跨模块清理；对不支持输入给负例，不能只测正常路径或逐行复制实现逻辑。依赖方向/源文件规模遵循已有 policy；新语言或工具必须同步真实构建/锁文件/静态检查，不能因文件后缀未登记而躲过门禁。

依赖升级单独列用途、固定版本、锁文件、许可证及与 Arrow/格式/协议的联编影响；更新前后保留同负载测量和兼容结果。基础依赖由锁文件安装并 `pip check`；数据库 toolchain/Cargo.lock 在首次内核切片固定，不能用浮动版本换取本机偶然通过。

公开接口/结果类型、能力白名单、持久布局或配置默认值改变时，同步 schema、示例、能力发现、兼容/迁移和回滚说明。默认不把“兼容”写成全量承诺；任何仍需补齐的测试以缺口记录，不把 TODO 当 ready。

## 3. 验证、复核与完成标准

顺序是局部复现/单元 → 影响范围功能与负例 → 对应组件性能/故障 → 需要的集成/完整实验。只在新修改、新失败或尚未解决风险时扩大/重复测试；不为碰到一次绿色而反复重跑。自动 required suites 是最低义务，不能代替风险分析。

完成前必须同时具备：

- 用户场景与验收案例满足，范围/拒绝行为有说明，相关文档/契约/示例一致；复核用户文档先于行为实现的记录，并逐项绑定成功/负例、实际命令和报告，未测项保留缺口。
- 所需门禁实际运行，功能、性能和稳定性证据分别陈述；缺失、超时、不可比较均不通过。
- 单独的复核轮次检查边界、复杂度、权限、版本/恢复和测试真值；高风险由独立审查轮次或人工复核，摘要写发现与处理。工具保存 review 文字，不自动证明复核独立性。
- 有限切片提交后，在干净树对**任务原始 base**再检查；最终 commit、指纹、范围和证据相符。PR 按依赖串行合入 `main` 后，在独立干净 worktree 对合并前主线基点检查全部合入范围并建立主线 checkpoint；分支 task-finish 只是分支验收，主线交付还需 PR或用户授权直接main提交及提交后本地证据；当前不要求远端CI success，见[CI暂停规则](ci-cd.md)。无 active 任务时显式 `--base <starting-commit>`，不能用空差异的检查替代任务验证。
- 兼容/迁移、数据/外部副作用、已知限制、恢复点与后续事项清楚；最终汇报已完成、实际命令/报告、commit、checkpoint 和未覆盖项。

```sh
# 实现/复核后选择性 stage 并 commit；pre-commit 校验提交快照
.venv/bin/python scripts/harness.py check
.venv/bin/python scripts/harness.py task-finish \
  --report artifacts/harness/<run>/report.json \
  --review '填写复核发现、处置与剩余限制'
```

`task-finish` 要求 clean、当前 commit/checkout 匹配、change/release 覆盖原始 base；bootstrap、空结果、缺 suite、失败命令、缺/被修改日志均拒绝。工具重新计算变更与所需门禁，验证 command 结果和 SHA-256，再创建完成 checkpoint、归档证据并结束 receipt。校验结构和摘要不能证明真实 driver 诚实，完整发布仍需真实实现、受控实验与复核。

## 4. 失败、取消和上下文交接

首次失败记录命令、输入/seed、错误分类、源码/数据版本与日志，再确定是假设错误、实现缺陷、环境前提还是产品边界。每次修复/重试说明新的假设；同一条件连续两次无新证据失败时停止盲试，做根因定位或缩小切片。网络等暂时错误遵守有限次数/总时间预算；不删除负例、抬阈值、换数据/缓存或关闭 hook 来消除失败。

中断/上下文恢复从 `task-status`、Git diff、变更计划和最近失败报告继续，写当前假设、已完成、下一步和未解决风险。需要终止/让出任务时使用 `task-abandon --reason '原因、保留现场与交接位置'`，仅归档状态，文件/提交/检查点不动；任务不会被标为完成。若任务锁在进程崩溃后残留，先读取锁中的 PID 并确认该任务进程已退出，再人工移除该锁，禁止自动抢锁。

遇无法继续的错误先停止副作用、保留现场，按[恢复流程](version-control.md)在新 worktree 恢复。代码 rollback 不恢复业务数据。持久协议变更必须分别写升级前提、旧 reader/writer 支持、进行中作业/pin、备份/恢复点、未知提交对账、降级/回滚兼容窗口；有破坏性迁移时优先恢复演练或向前修复，不能简单回退二进制后宣称恢复。

## 5. 证据生命周期

每次 check 记录 selection_base、commit、checkout digest、各命令与日志 SHA-256，检查过程中 HEAD/源码变化使报告失效。成功 checkpoint/task-finish 重新验证完整记录，并将 report、日志和路径映射归档到共同 Git 管理目录 `guradb/evidence/<report-sha>/`，避免 artifacts 清理后只剩 tag 摘要。旧格式报告缺这些字段时重新运行，不补填成功结果。

自动归档的范围是 harness 报告和命令日志；benchmark 原始测量、故障 trace、构建物和大数据清单需要 driver 单独归档。task-finish 不等于这些外部引用都已被复制，清理前逐项确认其可取副本。

receipt/本地归档不在源码 commit 或 Git bundle 中，不等于远端审计、异地备份或防篡改存储。CI 上传失败日志，候选发布/性能基线的完整报告、环境、固定数据清单和 trace 必须在有效期前转存到已授权的持久存储；只有确认已有可取副本才清理本地。诊断日志由 driver 脱敏，禁止记录凭据或默认泄露敏感参数。

CI/CD 分层与 GitHub 接入步骤见 [GitHub Actions](ci-cd.md)。
