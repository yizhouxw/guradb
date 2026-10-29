# GuraDB Agent 工作约定

2026-10-29 当前产品范围以[单机Rust alpha](docs/user/simple-alpha.md)及
[ADR0028](docs/decisions/0028-simple-rust-alpha.md)为准：可信单用户、单本地固定Parquet、
单Rust CLI。旧Python在线、HTTP/PG、检索/worker操作已实际退役；历史能力与长期产品
义务不作当前用例前置。技术入口为[当前harness](harness/README.md)，协作职责规则不变。

## 开始与恢复

先阅读 [README](README.md)、受影响目录的 AGENTS、对应 ADR 和 [harness 入口](harness/README.md)。长任务/上下文恢复时检查 Git 状态、当前变更计划、未解决风险与最新报告；旧摘要里的“通过”不能替代当前代码证据。

团队职责、技术升级、本地任务与稳定成员派发以[团队协作规范](harness/team-collaboration.md)为唯一入口。PM全项目唯一执行会话，亲自负责目标、排程、组织与协作harness治理；产品技术执行由统一开发负责人按目标委派subagent并自主完成验收交付链。活跃成员仅PM/产品/架构/开发/测试五角色，模块是领域知识，集成为开发职能。非PM成员可多执行实例，身份与项目内成员记忆绑定而非session。只在结果、阻塞或越界时沟通，任务恢复按需加载最小上下文。

离线恢复先读 [PM START](harness/pm/START.md)、[本地任务](harness/tasks/README.md)与[成员记忆](harness/members/README.md)；GitHub Issue仅为可选外部ref，原#19协调模式/动态评论/长期约束索引明确撤销，禁止用于派发或恢复；普通分支/PR保持，见[ADR0026](docs/decisions/0026-goal-driven-collaboration.md)；[ADR0025](docs/decisions/0025-local-member-memory-and-task-delegation.md)保留历史来源。

默认中文说明，英文代码标识符。按需加载相关文档，不把全部历史塞进上下文；长期决定进入 ADR，根文件保留导航和全局规则。

## Git 追溯与恢复

遵循 [Git 工作流](harness/version-control.md) 与 [ADR 0008](docs/decisions/0008-git-traceability-and-recovery.md)。开始记录 `git status`、起始 commit/分支与检查点；不能自动 stage/stash/覆盖已有用户改动。

当前采用 [GitHub PR 并行流程](harness/parallel-development.md)与 [ADR 0019](docs/decisions/0019-pr-parallel-development.md)：所有开发任务（含文档）默认使用 `codex/<task>` 分支，每个并行任务独占 worktree、task receipt 和文件范围；通过本机适用自测与独立复核后由集成者按依赖顺序串行合入 `main`，不直接向主线提交或推送。失败现场恢复仍在新目录。2026-10-26治理任务曾获单次直接main授权，仅适用于该历史任务；后续治理与普通任务仍默认独立分支/PR。该约定替代此前普通任务直接 main 的规则；已存在的 dirty 任务保留原现场，迁移办法见流程。

有限切片通过门禁和复核后提交，记录变更、验证与恢复点；提交后生成精确绑定新 commit 的检查报告并建立 checkpoint。本仓库作者使用 `yizhouxw <yizhou.xw@gmail.com>`。用户已授权本仓库后续开发在门禁和复核通过、提交后验证完成后直接推送任务分支到现有 `origin` 并创建 PR，满足合入条件后通过 GitHub PR 合入 `main`，不再逐次询问；不得强推或覆盖远端新提交。当前已获用户授权暂停GitHub Actions CI/CD和PR远端CI准入，见[ADR0023](docs/decisions/0023-team-issues-and-local-quality.md)；其余远端设置和部署仍需另行授权。禁止为过门禁使用 `--no-verify` 或关闭 hook。

非小型任务按[开发流程](harness/development-workflow.md)使用 `task-start --label ... --objective ...` 固定基点；plan/check/pre-commit 自动覆盖整项任务。恢复先读 `task-status`，最终提交后执行 check，再用 `task-finish --report ... --review ...` 核验原始范围、归档证据并结束。停止/交接用 task-abandon 保留现场，不把它标成完成。

遇到阻断错误先保留日志/diff/失败现场，用 `harness.py recover` 在新目录恢复 checkpoint；需要撤销主线提交时在干净树用经复核的 revert 新提交。默认禁止破坏性 reset/clean、强制 checkout、强推或重写共享历史。代码恢复不撤销数据迁移和外部副作用，必须独立对账/补偿。

## 产品与架构边界

- [ADR 0002](docs/decisions/0002-object-store-lake-boundary.md)：对象存储湖架构，不做高并发 OLTP/实时敏感业务事务。
- [ADR 0003](docs/decisions/0003-storage-and-execution-baseline.md)：Rust/Arrow/DataFusion、Iceberg/Parquet、Lance/Tantivy/邻接和小型 PG 控制面为推荐 POC 基线，其中 M0 Rust/Arrow/DataFusion/Parquet 受限路径已落地，后续组件仍待验证，见 ADR 0010。
- [ADR 0004](docs/decisions/0004-snapshot-and-index-publication.md)：事实数据有唯一权威来源，默认读已发布 read view；数据提交与索引就绪分离。
- [ADR 0007](docs/decisions/0007-incremental-delivery-and-gates.md)：按路线图切片实施；身份/版本/保留遵循[数据合同](docs/product/data-contracts.md)，组件验证与完整产品发布分别验收。
- 需求、推荐设计、已接受决定与已实测能力分别描述。不得把骨架/目录/契约或模拟测试写成已支持功能。
- PG18 语法/类型、wire、目录、事务、扩展分别验收；格式按版本、方向、删除/schema/快照语义验收，不解析后忽略不支持行为。

## 阶段优先级

按[分阶段验收策略](harness/validation-strategy.md)、ADR0027及ADR0028执行。当前合法核心入口为
`--stage core --core-flow simple-alpha`，自动沿用active receipt原始base并验证实际退役、
新Rust源、真实CLI与进程清理；报告只声明core-limited。强化/发布覆盖、兼容/故障矩阵、
性能和长稳义务保留，缺证据不得称通过；普通hook/PR不绕过，Actions/部署保持暂停。

## 每次变更的闭环

1. 用户可见开发先更新 [用户手册](docs/user/README.md)，写明场景、操作、预期、支持/拒绝、权限/预算及兼容/恢复，新增部分先标待实现，再修改行为代码。按[场景模板](harness/templates/user-scenario.md)保存先行合同与验证映射；完成时复核成功/负例和实际证据，缺失验证不得标支持。纯内部改动记录无用户行为影响的依据，纯文字修订可轻量验证；详见 [ADR 0016](docs/decisions/0016-user-documentation-first.md)。运行 `.venv/bin/python scripts/harness.py plan`；对拟议文件可用 `--path` 预判风险。
2. 跨模块、热点、持久化/发布/GC、基线变化使用 [变更计划](harness/templates/change-plan.md)，写清不变量、最小切片、功能真值、性能预算及故障断言；小型文档修改不强制填表。
3. 实现相关行为与负向测试，避免捎带重构。改变公开接口/布局时同步文档、示例、兼容与迁移说明。
4. 运行 `.venv/bin/python scripts/harness.py check`，按[策略 v2](docs/plans/2026-10-21-modular-delivery-v2.md)区分模块、真实配对、系统、发布。常规模块验证其完整 owner 源码和自身真实依赖；跨包可用固定 fixture。系统回归排入集成窗口，发布完整义务保留。机器 selector 未接通/映射未知时明确扩大或拒绝，不能伪称模块门禁已通过；缺失命令/证据、超时或失败不得跳过成绿。
5. 单独审查差异、复杂度、边界和证据；高风险变更需要独立审查轮次或人工复核。
6. 报告改了什么、为什么、实际命令和报告、缺失证据及风险。仅 bootstrap 通过不得宣称数据库质量通过或可发布。

开始前写用户可观察验收、范围与支持/拒绝白名单；完成标准、依赖/迁移纪律、两次无新证据失败后的根因定位及交接遵循开发流程。当前暂停[GitHub Actions CI/CD及PR CI准入](harness/ci-cd.md)，以本机自测、独立复核与精确main证据保障合入；模块、真实配对、系统和release分别验收。原功能/性能/故障/长稳及预算不变，恢复CI/CD另行讨论授权。

Python仅保留工程和独立fixture用途，安装与make替代入口见[harness/README](harness/README.md)。
当前唯一生产源为crates/guradb；历史M0/M1/M2及在线Python demo已退出支持，见
[实际退役清单](harness/alpha-retired.json)。当前核心Rust/CLI检查与未来完整发布分别验收。

## 全局质量不变量

[机器清单](harness/invariants.toml) 是验证义务，不是覆盖证明。尤其不能破坏：

以下目录/索引/授权/远端/pin义务保留给未来相应功能，不冒称当前单机CLI已实现这些平台；
当前alpha实际验证固定源bytes、输入拒绝、内存/I/O/输出边界及进程终态。

- 稳定逻辑 ID/记录版本不依赖物理 rowid；扫描、ANN、全文、图路径与分页读同一固定视图。
- 索引缺口要补偿/等待/报错；旧构建不能倒退发布，源提交 fencing 与目录发布 fencing 分别验证。
- 提交结果未知先对账；GC 检查源引用、快照、查询与训练 pin；撤权不被缓存/旧索引绕过。
- 取消、内存、远程请求、图扇出与执行预算贯穿远端任务；派生索引不得变成独立双主。
- ANN/融合/训练优化同时证明结果与质量，不能通过漏读、降低 recall、缩小负载或换暖缓存声称提速。

## 规模与证据纪律

- 遵循 [architecture.toml](harness/architecture.toml) 的唯一归属与依赖 DAG；公共类型不能反向依赖上层，不建立多套客户端语义。
- 源文件上限 600 行；按职责拆分，不压缩代码规避。新增语言补充实际依赖/静态检查，当前 Cargo 检查不证明其它语言 import 图。
- 功能采用独立真值/差异/属性/负例；性能固定输入和环境，区分冷热并计请求/字节/内存/构建；稳定性记录 seed、注入和恢复 trace。
- 禁止手填/复用不匹配的性能结果、把 synthetic 结果写成产品 baseline、删用例或调预算消除回归。基线/门禁削弱需前后证据与独立复核。
- 不提交凭证、用户数据、大型媒体或运行产物。日志放 artifacts，不把敏感参数写入证据。
- 只使用本项目约定，不沿用其它仓库的分支/提交/推送规则。
- 在制槽、共享写权、作者与独审分离及交付记账统一遵循[团队协作规范](harness/team-collaboration.md)，不在会话提示中另设职责规则。

## 强化/发布覆盖义务（2026-10-24阈值，2026-10-28调整适用阶段）

Python 全部自研生产源行覆盖率至少80%；Rust仍为现有经审查排除后的适用行100%。两者用合法整数covered/total交叉相乘判断，total必须大于0，不用显示百分比或舍入。完整源分母、未导入文件、身份前后绑定、测试失败拒绝保持；Python仍不允许行排除，Rust原21行清单不扩大。旧100%要求/历史报告保留为当时合同，不改写原失败或测量。本次政策实现与边界验证另记；80%不等于完整产品验收。
