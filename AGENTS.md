# GuraDB Agent 工作约定

## 开始与恢复

先阅读 [README](README.md)、受影响目录的 AGENTS、对应 ADR 和 [harness 入口](harness/README.md)。长任务/上下文恢复时检查 Git 状态、当前变更计划、未解决风险与最新报告；旧摘要里的“通过”不能替代当前代码证据。

默认中文说明，英文代码标识符。按需加载相关文档，不把全部历史塞进上下文；长期决定进入 ADR，根文件保留导航和全局规则。

## Git 追溯与恢复

遵循 [Git 工作流](harness/version-control.md) 与 [ADR 0008](docs/decisions/0008-git-traceability-and-recovery.md)。开始记录 `git status`、起始 commit/分支与检查点；不能自动 stage/stash/覆盖已有用户改动。

当前按单人开发约定：普通任务默认直接在 `main` 开发并完成提交；已有工作分支开发完成后合并到 `main`。只有并行开发同一大需求时才使用多分支，每个分支对应独立 worktree，完成后合回 `main`。失败现场恢复仍按安全恢复流程保留在新目录。

有限切片通过门禁和复核后提交，记录变更、验证与恢复点；提交后生成精确绑定新 commit 的检查报告并建立 checkpoint。本仓库作者使用 `yizhouxw <yizhou.xw@gmail.com>`。用户已授权本仓库后续开发在门禁和复核通过、提交后验证完成后直接推送到现有 `origin`，普通任务推送 `main`，不再逐次询问；不得强推或覆盖远端新提交。远端设置和部署仍需另行授权。禁止为过门禁使用 `--no-verify` 或关闭 hook。

非小型任务按[开发流程](harness/development-workflow.md)使用 `task-start --label ... --objective ...` 固定基点；plan/check/pre-commit 自动覆盖整项任务。恢复先读 `task-status`，最终提交后执行 check，再用 `task-finish --report ... --review ...` 核验原始范围、归档证据并结束。停止/交接用 task-abandon 保留现场，不把它标成完成。

遇到阻断错误先保留日志/diff/失败现场，用 `harness.py recover` 在新目录恢复 checkpoint；需要撤销主线提交时在干净树用经复核的 revert 新提交。默认禁止破坏性 reset/clean、强制 checkout、强推或重写共享历史。代码恢复不撤销数据迁移和外部副作用，必须独立对账/补偿。

## 产品与架构边界

- [ADR 0002](docs/decisions/0002-object-store-lake-boundary.md)：对象存储湖架构，不做高并发 OLTP/实时敏感业务事务。
- [ADR 0003](docs/decisions/0003-storage-and-execution-baseline.md)：Rust/Arrow/DataFusion、Iceberg/Parquet、Lance/Tantivy/邻接和小型 PG 控制面为推荐 POC 基线，其中 M0 Rust/Arrow/DataFusion/Parquet 受限路径已落地，后续组件仍待验证，见 ADR 0010。
- [ADR 0004](docs/decisions/0004-snapshot-and-index-publication.md)：事实数据有唯一权威来源，默认读已发布 read view；数据提交与索引就绪分离。
- [ADR 0007](docs/decisions/0007-incremental-delivery-and-gates.md)：按路线图切片实施；身份/版本/保留遵循[数据合同](docs/product/data-contracts.md)，组件验证与完整产品发布分别验收。
- 需求、推荐设计、已接受决定与已实测能力分别描述。不得把骨架/目录/契约或模拟测试写成已支持功能。
- PG18 语法/类型、wire、目录、事务、扩展分别验收；格式按版本、方向、删除/schema/快照语义验收，不解析后忽略不支持行为。

## 每次变更的闭环

1. 用户可见开发先更新 [用户手册](docs/user/README.md)，写明场景、操作、预期、支持/拒绝、权限/预算及兼容/恢复，新增部分先标待实现，再修改行为代码。按[场景模板](harness/templates/user-scenario.md)保存先行合同与验证映射；完成时复核成功/负例和实际证据，缺失验证不得标支持。纯内部改动记录无用户行为影响的依据，纯文字修订可轻量验证；详见 [ADR 0016](docs/decisions/0016-user-documentation-first.md)。运行 `.venv/bin/python scripts/harness.py plan`；对拟议文件可用 `--path` 预判风险。
2. 跨模块、热点、持久化/发布/GC、基线变化使用 [变更计划](harness/templates/change-plan.md)，写清不变量、最小切片、功能真值、性能预算及故障断言；小型文档修改不强制填表。
3. 实现相关行为与负向测试，避免捎带重构。改变公开接口/布局时同步文档、示例、兼容与迁移说明。
4. 运行 `.venv/bin/python scripts/harness.py check`，根据实际变更选择门禁。缺失命令/证据、超时或失败不能跳过成绿。
5. 单独审查差异、复杂度、边界和证据；高风险变更需要独立审查轮次或人工复核。
6. 报告改了什么、为什么、实际命令和报告、缺失证据及风险。仅 bootstrap 通过不得宣称数据库质量通过或可发布。

开始前写用户可观察验收、范围与支持/拒绝白名单；完成标准、依赖/迁移纪律、两次无新证据失败后的根因定位及交接遵循开发流程。CI/CD 采用 [GitHub Actions 分层方案](harness/ci-cd.md)，此前 bootstrap CI 已通过；新运行时变更需推送后验证，CD 待发布/环境合同。

Python 3.11+ 开发依赖安装与 make 替代入口见 [harness/README.md](harness/README.md)。当前 M0/M1 有界读取及部分 M2/本地三 worker 切片已落地，范围见 docs/design/m2-running.md；rust/functional/performance-smoke/stability-component 为 ready，完整 performance/stability/soak 仍 planned。组件通过不等于完整发布通过。

## 全局质量不变量

[机器清单](harness/invariants.toml) 是验证义务，不是覆盖证明。尤其不能破坏：

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
