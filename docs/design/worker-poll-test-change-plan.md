# 变更计划：remote worker 输出轮询边界的确定性测试

状态：新head初检通过；提交后验证、PR与精确main验收仍待完成。原819候选的两条单元与Python-only覆盖仅为历史局部证据。仅测试稳定性切片，不依赖 CF1-A，也不属于 P05 SQL 机械拆分。

原任务 Git：分支 `codex/worker-poll-coverage`，起始 commit `8198658bc768a96638ad70a12948f3775a5cbab2`，独立 worktree `/Users/chad/dev/guradb-worker-poll-coverage`，起始树干净。task receipt `7e5a987105434db1a28120c3771c76df`，checkpoint `checkpoints/20261021T013120Z-before-worker-poll-coverage-6d2d547b`。原dirty目录及证据保留，不修改或删除。

接续 Git：从原 checkpoint 安全恢复至新目录 `/Users/chad/dev/guradb-worker-poll-recovered`，建立分支 `codex/worker-poll-coverage-recovery`；在HEAD仍为819且树干净时启动新receipt `329ca8938276445eb79e4520e1b24e65`，checkpoint `checkpoints/20261021T015411Z-before-worker-poll-coverage-recovery-056e559e`，原始base仍为819。随后在clean树正常快进合并精确main `4d6baca888421d90f146679ef71b0e555fe60881`，再经apply检查重放两文件候选。迁移补丁SHA `99d5a08530d6fc4a0f0202884b3f3021322cbfc582ca4b8f12eae4581c9fadd0`，测试SHA仍为 `4f4f7a0a404e82596746e72f213185540a2f07dcc2dd79e4d928687fda18582a`。恢复记录、原候选与历史证据只读归档于 `artifacts/worker-poll-coverage-recovery`，历史覆盖计数不用于新head。

本任务独占文件为本计划及 `tests/unit/test_remote_units.py`；不修改生产源码、SQL、依赖锁、coverage 阈值或排除清单。新receipt范围包含合入的P00历史，但本片没有新增其合同或运行时实现。

## 需求、实际根因与非目标

P05 首轮完整初检的八个 suite 通过，但 `unit-coverage` 因既有 `modules/query/remote_worker.py:190` 未覆盖而失败；183 项 Python 测试本身通过，Python 为2967/2968，Rust 为适用2243/2243。失败现场保留在独立 SQL worktree 的 `artifacts/query-core-extract/initial-failure`，原报告为 `artifacts/harness/20261021T011620Z-0add0830/report.json`，报告 SHA `5cb5e9ad6216fb18f61ea62cae8e16ba3ca9c9a424d9d9c14763725c5566b24b`。

该行在 `Tasks.run` 中仅当子进程仍在运行且输出文件已出现时检查文件大小。当前真实短进程在最后写输出后立即返回，10ms 轮询可能直接观察到已退出进程，随后仍会执行最终大小检查。既有单元使用真实进程，却没有固定这一中间窗口。最近成功的 PR7 exact-main `84c07af2` 覆盖了该行；该 commit 到本任务基点只有两份计划文档变动，相关生产源码、测试和 coverage 配置逐字相同。这是静态证据支持的时序敏感覆盖缺口，未通过重复测试实验确认所有调度条件。

本片为 [ADR0012](../decisions/0012-bounded-p0-and-local-workers.md) 既有本地 worker 资源限制补确定性正例与负例。它不修改 worker 轮询、资源上限、清理算法或外部能力，不将受控替身测试写成真实多机、性能或生产发布证据，也不删除原真实进程测试。

## 用户文档先行与验收边界

本计划先于测试源码编辑保存，先行 patch 放在 ignored `artifacts/worker-poll-coverage/docs-first.patch`。仅增加对现有行为的回归验证，不改变用户操作、API、结果、错误、权限、预算、持久格式或默认配置，依据 [ADR0016](../decisions/0016-user-documentation-first.md) 记录无用户行为影响，不修改用户手册。

验收固定两类输入：存活子进程已产出合法小结果时保留完整身份与返回值；存活子进程已产出 `MAX_BYTES+1` 的结果时，在读取/接受结果前以 `resource_limit` 拒绝。两条路径都必须在 `finally` 中恰好调用该进程的 `stop_group`。使用临时目录和受控 Popen/poll，显式固定输出先于首次 poll；超限文件用 truncate，避免分配大内存。禁止靠 sleep 碰窗口或重跑换绿。

## 风险、不变量与实施步骤

本片强化既有执行预算与取消清理义务，不改变任何身份/版本、发布、GC 或撤权边界。Popen 替身仅用于确定性单元，原真实进程合同保留。正例必须完成真实临时文件写入/读取与现有身份校验，负例必须断言准确错误码与 finally 清理，避免仅执行目标行而不验证行为。

1. 保存计划、失败对照与原测试源码摘要，运行仅风险规划的 `plan`。
2. 在原测试文件补两条受控轮询单元；不调整原测试和生产实现。
3. 交 root 独立审查恢复后的候选差异与新plan；按窗口授权运行小型单元，完整check须复核新plan后另获窗口，不自行进入hook或提交。
4. 等独立窗口运行新增局部单元、Python 覆盖检查及 harness 选出的原始 task 全范围门禁。所有验证须绑定当前源码，失败保留现场；两次无新证据失败先定位根因。

无数据迁移或外部写入；恢复点为上述 checkpoint。中断保留独立 worktree 和 task receipt，未满足验证与独立复核不得 task-finish、提交或推送。

## 验证合同与结果

测试固定合法结果、超限一字节、进程 poll 顺序及进程身份，不使用 wall-clock 延迟制造命中。预期合法结果被返回、超限准确拒绝，两个 finally 清理都被断言。性能预算、固定镜像和覆盖率门槛全部不变；无性能优化声明。

候选已在原测试文件增加两条单元：合法输出固定 `poll` 为 running→exited，核对完整结果、两次 poll、一次轮询等待及 finally 清理；超限输出使用 `MAX_BYTES+1` 的 truncate 文件，要求首次 running poll 内报 `resource_limit`、不等待下一轮、returncode 仍为空并清理同一进程。原测试逐字保留。root已独立阅读原候选差异，无阻断；恢复后测试源码逐字一致，文档接续信息仍需复核。

原819候选在短窗口中运行两条targeted unit，2/2通过；独立Python-only严格coverage的185项测试通过，2968/2968行、零排除且目标行190已覆盖，前后源码身份一致。原证据为旧目录 `artifacts/worker-poll-coverage/python-initial`、`targeted-unit.log` 与 `short-window-result.json`；完整历史证据归档SHA为 `958260cb1ea2679721c83afab3283c91c77f5981c67d6cba7c183d7a20c6830d`。这仅是旧候选局部证据，不是恢复后新head的完整通过，也不改变原P05初检失败状态。

原819未合入P00时风险规划为5项。恢复后新receipt继续以819为原始范围，实际plan包含P00合入，选择 contracts、functional、harness-tests、performance-smoke、policy、python、repository、rust、stability-component、unit-coverage 共10项；影响common及反向模块DAG、INV-001至012，记录在 `artifacts/worker-poll-coverage-recovery/candidate-plan.json`。

新目录在HEAD `4d6baca888421d90f146679ef71b0e555fe60881`、原始base819范围完成首次完整 `harness.py check`：10项suite、26条命令全部通过；Python3365/3365、零排除，目标行190已覆盖；Rust适用3323/3323，保留原21条排除。报告为 `artifacts/harness/20261021T020154Z-a37830fe/report.json`，SHA `91b8a4060662d02f3ac0969c550930deb4bd803e6d6f4f5153f2b801af6ce786`，checkout digest `df9b5654ee337a3d3e9b2652afee70260dc51f8293d75b0e48c167eb02b1cef0`。作者与root分别核验了完整原始范围、当前源码和全部命令/日志SHA；root源码复核仍通过。结果摘要保存在 `artifacts/worker-poll-coverage-recovery/initial-check-result.json`。

该报告绑定结果更新前的计划SHA `8b5167344b791389ba4285ecabc9dc8a3e22214cb4385f08369e1c01440fe08a`；本轮只更新结果文字，测试源码SHA仍为4f4f7a0a。当前尚未进入hook或提交；提交后原819范围check、task-finish、PR双版本CI及精确main/主线CI均待验收，不把初检或历史partial写成最终交付。推送与PR由root后续串行处理；P05原失败现场保持不变。
