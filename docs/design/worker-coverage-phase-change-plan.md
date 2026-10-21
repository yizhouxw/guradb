# 变更计划：覆盖率门禁阶段证据

状态：先行源码已独立复核，获独占窗口进入针对性验证，完整门禁待运行；尚未进入hook或提交。依据 [ADR0016](../decisions/0016-user-documentation-first.md)，这是工程诊断内部变更：不改变数据库 API、查询结果、权限、数据格式或用户操作，不新增产品支持声明，因此用户手册不变。

Git：worktree `/Users/chad/dev/guradb-worker-poll-recovered`，分支 `codex/worker-poll-coverage-recovery`，干净起点 `fb41388fe7a9f22b6598323e56c14bc48e9fa1da`。新 receipt `df6603844f5246e4b9d1590a94afdc58`，label `worker-coverage-phase-evidence`，checkpoint `checkpoints/20261021T031209Z-before-worker-coverage-phase-evidence-326fc4bc`；上一 worker task 已完成，历史证据保留。当前 follow-up 的原始 base 是 fb41388；PR10 原始范围仍从 `8198658bc768a96638ad70a12948f3775a5cbab2` 开始，最终提交后及 PR 验证须显式覆盖完整原819范围，不能仅用新 receipt 缩小验收范围。

## 失败事实、范围与非目标

PR10 run `39534778690` 的同一测试 merge `a4ee156e74e243678333144118110b1eac0ec0b6`、相同 checkout digest，Python3.14 的 `unit-coverage` 命令在 480.043 秒被 harness watchdog 终止（timeout，-9）；Python3.11 对照在 396.158 秒完成。失败运行 Python3365/3365、零排除，目标 `remote_worker.py:190` 已执行；Rust 单测已打印通过，但 Rust JSON/LCOV/summary/result 未生成，Rust 覆盖验收缺失。插桩构建分别为 5m23 与 3m51，相差92秒；证据支持冷构建/运行成本耗尽工具命令预算，尚不能细分最后一个 Rust 阶段或断言语言/LLVM 缺陷。准确报告、ZIP、日志与 SHA 保留在 ignored `artifacts/worker-ci-failure/diagnosis.json`（SHA `117630539eb096638b5e81eadab0bcba1735482a8d9fd9501aea4542747ed35c`），不得抹去本次 CI 失败。

独占文件域：本计划、`scripts/unit_coverage.py` 和新增 `tests/harness/test_unit_coverage_phases.py`。保留原覆盖率 harness 测试、两条 worker 测试、生产源码、所有旧命令 argv、实际测试发现、全源码分母、严格零缺失/零 Python 排除及原21条 Rust 排除逐字不变。不复用 coverage 计数、profile、报告，不新增缓存，不调整产品性能/故障/质量阈值，不顺带重构 coverage_policy 或 runner。

最初拟议工具命令预算由480秒改为900秒，作者只提交建议；`harness/policy.toml` 由 root 唯一持有，后续串行候选变更见下段。root 须结合上述 before 证据、独立审查和 after 实际本地/双版本 CI 结果验收，不能靠旧报告、删除测试或缩小覆盖范围判绿。

root串行接管整树后，将该建议纳入本轮**待验收候选**：仅把unit-coverage命令watchdog由480改为900秒，新增文件域为root独占的`harness/policy.toml`单行。两平台测试相同merge/checkout，Rust生产源码、Cargo/依赖锁和实际Rust命令相同；92秒冷插桩构建差异超过成功方83.842秒余量，原失败没有性能/覆盖断言回归证据。这是明确的工程门禁执行预算调整，不能描述为预算未变；900尚未证明是所有环境的充分上界。保留原失败与对照，阶段记录须让下一次运行明确未完成边界。所有数据库性能/故障/取消预算、测试发现、源码分母、100%覆盖要求和21条排除保持原样；不新增缓存或借用计数。

本段与实现前policy原文/摘要先保存于ignored artifacts后才修改该单行，再交非作者p00独立复核。实际after必须包括当前本地原819完整范围和当前head双版本PR CI，以及精确main/主线CI；未取得全量JSON/LCOV/summary/identity/result前不能称覆盖通过。原480秒CI仍失败，后续结果单独记账；若900仍超时，保留阶段证据定位，不自动再抬时限。

## 增量证据合同与实现步骤

每次现有 CLI 继续要求全新、workspace 内的独有 `--run-dir`，新增 `phases.jsonl` 也以独占创建拒绝复用。每条记录立即 append、flush、fsync；先落盘 `started`，才调用该阶段。正常完成写 `finished` 与 monotonic duration；返回 False 写拒绝失败，异常（含 BaseException）写失败类型后重新抛出，不记成功。父 watchdog 的 SIGKILL 无法补写失败，未配对 started 表示未完成，不推断成功或具体内部失败点。

边界为现有 Python 测试及报告整体、Docker image build、现有 `cargo llvm-cov --workspace ... --json` 的编译/测试/JSON整体、现有 LCOV report、Rust inventory/summary；同一个 cargo CLI 不拆成虚构的 compile/test/export 子测量。整体语言阶段和前后源码身份也留边界。记录当前 git/checkout、Python/coverage 版本、锁文件与工具 Dockerfile 摘要；构建后独立观察 Docker image ID，明确其观察时点与所用 tag。额外只读 image inspect 不替换或重排原有 build/run argv，不把浮动 tag 当不可变工具身份，也不复用旧计数。

先保存本计划与实现前 diff/hash，再实现最小阶段 journal 与专用 harness 单元。冻结 manifest/diff 给 root/p00 独立审查；本轮不执行任何测试。获窗口后依次验证局部 harness 正负例、required suites、原819全范围提交后验收与真实双版本远端 CI。文档、模拟负例与阶段文件存在不能替代实际全量覆盖通过。

## 验证合同、恢复与当前结果

专用负例在回调真正执行前读取 journal，证明 started 已持久化；随后受控 TimeoutExpired/中断必须留下失败类型、不得产生 finished，异常仍传播。返回 False 必须为拒绝失败；正常阶段必须记录可重算的 monotonic duration。Rust 子命令失败应阻止后续 collect/LCOV/summary，并保留开始边界；原 harness 的分母、缺行、测试失败和并发 profile 拒绝用例保持原样。使用临时目录和受控时钟/回调，不启动 Docker、不靠 sleep 碰时序。

新增开销为少量固定边界的 JSONL/fsync、源码/锁文件摘要及只读 image identity 查询，不声称性能优化；实际开销和真实阶段分布待 after 证据。故障记录不包含异常消息、环境变量、凭据或外部 DSN。写证据失败本身使门禁失败，不以诊断失败静默吞掉覆盖义务。

候选已编写阶段 journal 与7条专用 harness 用例，包括通过管道握手后真实终止阻塞子进程的持久边界负例；初次冻结时所有新增用例与原覆盖率门禁均未执行。先行记录位于 ignored `artifacts/worker-coverage-phase-evidence/docs-first.json` 和 `plan-before-behavior.md`。当前计划的风险规划选择 contracts、harness-tests、policy、repository、unit-coverage 共5项；最终原819完整范围的门禁不得由这份局部规划替代。PR10原480秒CI仍失败且未合入；当前900秒候选及阶段证据已独立源码复核，真实完整after门禁尚未开始，针对性结果见下文。

首次获窗执行新增7项及原4项 coverage harness targeted tests，10项通过、1项失败，未启动完整初检。新增 main 负例将 macOS TemporaryDirectory 的 `/var/...` 原路径注入 ROOT，入口把 run-dir 解析为 `/private/var/...`，触发既有 workspace 边界拒绝；生产 ROOT 已由 `__file__.resolve()` 取得，此为新测试的路径身份错误。原4文件摘要、完整patch、raw log和实际路径对照保留在 ignored `artifacts/worker-coverage-phase-evidence/initial/first-failure.json`（log SHA `088ea509a53c4a8beb31cfab4c0c275b8976b389f3b27380656a2ac499223676`）。root独立读取后确认根因，授权只将该 main 负例的临时 ROOT 解析为物理路径；其余断言、测试、生产脚本和policy保持原样。修正后须使用新manifest与新日志重验11项，成功后才启动原819完整初检，旧失败保持失败。

中断保留该 task/worktree 与全部原 CI 证据；如需恢复，使用上述 fb 基点 checkpoint 在新目录恢复，不覆盖原现场。无数据库/对象写入或数据迁移副作用。


## 首次整仓失败与 CI 预算模型修订合同

原PR基点819的首次新完整检查 `artifacts/harness/20261021T033601Z-78c87b53/report.json` 整体失败：10suite中9项、26命令中25项通过，唯一失败为harness-tests内CI job预算断言；报告SHA `5931a47c48cbc9d3f0ff30da4a1d3e1858c71dadc3a1785558bfc20614dffe37`，checkout `a32dd2b40d171a2ca74ab5dc2b408d6f04baae285708b61ae4dcb9b8a3b18089`。Python3365/3365与Rust3323/3323、原21排除不变，各phase start/finished完整配对；本机已有编译缓存，21.172s Python与77.249s Rust不外推冷CI。全部原始日志/阶段/覆盖文件及失败patch在initial-v2保留，不能拼接为通过。

该失败不是产品性能退化：unit工具watchdog900使旧测试的change预算至少245min，而原job240min；该测试旧Rust代表路径漏Python，全部ready实际命令及600s安装/上传余量为14820s/247min。root与p00独立读取实际runner确认：planned suite只立即追加missing且不执行command，release因此失败；旧max(1,len([]))为三个不存在的完整gate虚计7200s，产生367min。GitHub-hosted单job硬上限6h/360min，不能盲将release写367，见[官方限制](https://docs.github.com/en/actions/reference/limits)。

在源码修改前冻结最小修订：普通job240→250min、release保持360；deadline测试改按全部ready可执行命令而非漏Python代表路径取change上界，release仍遍历原完整release_suites但只计实际执行的ready commands；600秒余量、所有suite命令/timeout/state/release义务、覆盖阈值/排除、900单命令预算不变。新增真实runner负例：存在运行时的release中planned gate不调用run_command且仍missing/整体失败；未来三完整gate变ready并有实际命令时必须重新计入7200s、超360的预算检查失败；显式拒绝hosted job设超过360。

该变化只修工程预算模型，无数据库用户行为影响，不增加partial证据协议，不改变missing不能通过的合同。未来新driver或ready范围增加后按真实命令重算，超过平台上限必须分段，不复用250作为永久充分时限。当前完整performance/stability/soak与release仍missing，不能据此宣称可发布。需独立源码复核及新原始范围完整check/PR两版本CI，旧失败保持失败。

## 本次完整初检结果与剩余验收

当前状态更新：root与p00已分别独立复核七文件候选，修正路径身份后的16项targeted tests通过；随后从原PR基点819显式执行完整INITIAL check，10项suite、26条命令全部通过。报告为 `artifacts/harness/20261021T035326Z-73211bb0/report.json`，SHA `5ee718ada9ee50b1bf727c5ec657cf0fa542ef87ae4775549350f87996ba8a84`，HEAD `fb41388fe7a9f22b6598323e56c14bc48e9fa1da`，checkout digest `361e31f33cedfccebb47dbf7035aa5e255b982462b5b623e0b7ba09251b85152`。该报告绑定结果更新前的本计划SHA `78d21d051fab9f01dcbf5fb71a6557804548eecf639c66af44faf60013925fbc`；上文“尚未运行”等文字记录的是先前冻结阶段，不能替代本段当前结果或未来最终head的证据。

Python3365/3365、零缺失/零排除；Rust适用3323/3323、原始3323/3344，原21条排除未变。9对phase started/finished完整配对、无failed，前后源码/输入identity一致；Python data/JSON、Rust JSON/LCOV/summary、phase、result和identity全部保留。作者重算26条命令日志SHA及七源SHA，root用匹配的项目解释器独立validate_report并逐项复核通过。完整命令状态与文件摘要为 `artifacts/worker-coverage-phase-evidence/initial-v3/full-initial-result.json`，SHA `7f4430b5164006284cfa5c7d561118fe321f52cee68d4c0b5adf7db0ee9c3ce1`。

阶段实测Python21.043秒、Rust73.320秒，其中collect/test/JSON为68.392秒、LCOV为3.350秒、summary为1.259秒。此为本机已有Docker/依赖/编译缓存的运行，仅证明该候选的本地检查与增量证据生效，不外推cold CI预算或产品性能。原480秒远端超时、targeted首次10过1错及033601完整初检9/10失败均原样保留，仍是各自版本的失败结果，不与本轮拼接为绿。

此次只追加owned计划结果，生产诊断代码、测试、policy和workflow保持冻结。当前尚未stage/hook/commit；最终提交后显式原819全范围check、task-finish、当前head双版本PR CI、精确main及主线CI仍待验收。文档结果更新会改变checkout身份，需由后续正常hook及最终head报告重新绑定，不能把本次INITIAL当作提交后或远端通过。推送与PR集成仍由root串行处理。
