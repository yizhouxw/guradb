# 变更计划：提取 legacy SQL 私有编译核心

状态：进行中；仅机械拆分，局部格式检查与 query crate 原有9项单元通过，完整门禁待初检。任务为 P05 共同计划实现前的共享热点准备，不消费 CF1-A，不表示 P05 或 I1 已开工/通过。

Git：起始分支 `codex/p05-query-core-extract`、commit `8198658bc768a96638ad70a12948f3775a5cbab2`，独占 worktree `/Users/chad/dev/guradb-p05-query-core`；起始树干净，无已有用户改动。task receipt `f55d47dea07c4bc99f46847e9475d2a7`，checkpoint `checkpoints/20261021T004426Z-before-p05-query-core-extract-c9a14128`。作者与 hook 已核对；源码准备期间只使用既有解释器运行标准库 harness，不占用 P00 门禁窗口。P00 释放窗口后，由 root 授予独立依赖安装与初检窗口；本轮初检结束先交还窗口，不自行进入提交 hook。

## 需求、范围与非目标

按[并行计划](../plans/2026-10-20-parallel-delivery.md)的共享热点拆分纪律，把既有 identifier/field lookup/parameter/typed expression Compiler 提取到私有 `compile` 模块，为后续按已冻结合同实施的独立 P05 切片保留清晰职责。遵循 [ADR0010](../decisions/0010-m0-bounded-manifest-reader.md)与 [ADR0014](../decisions/0014-bounded-pg-wire.md)，只有一套现有 SQL 白名单与执行编译器。

本任务独占 `crates/guradb-query/src/sql.rs`、`src/lib.rs` 的私有模块接线、新 `src/compile.rs` 及本计划；必要时机械适配原 `tests/unit/compiler.rs`，不新增测试语义。共享文件 `harness/coverage-exclusions.json` 由 root 单一 owner 仅机械重绑定原有 SQL 源摘要与行号，不增删豁免义务或修改分类、理由、行文本。禁止修改其他模块、common、公开 API、用户能力白名单、根计划、依赖锁或 harness policy。`describe.rs` 不改动，继续两次调用 `sql::prepare`，不复制其白名单或参数处理。

验收是外部行为不变：Prepared 的字段和公开 prepare/execute 路径保持原状；标识符规则、参数位置/数量/typed int8/NULL、表达式类型与深度、排序/投影/SQL LIMIT，以及 SQL/PG 错误边界均保持。不得新增 JOIN/聚合/类型/语法、CF1-A provider 或共同目录绑定。

## 用户文档先行与无行为影响依据

本计划先于源码编辑保存；先行 patch 记于 `artifacts/query-core-extract/docs-first.patch`。这是一项纯内部代码组织变更：移动已有私有实现并调整 Rust 模块内可见性，不添加公开 API 或改变用户操作、输入/输出、错误、默认配置、身份/权限、预算及持久格式，因此不修改用户手册。任何实际行为修正必须另立切片，不能借本任务实施。

## 风险与不变量

保持查询视图/逻辑身份、类型和 NULL、白名单拒绝及预算/取消调用路径不变；本片不改变持久化、发布、GC 或来源对象。`compile` 是 query crate 内私有模块，不增加模块 DAG 边。每份源码保持 600 行以内，不压缩代码规避。

`sql.rs` 既有五条 coverage-exclusions 以源 SHA 与精确行文本绑定；拆分仅改变行号/源码摘要，不能新增豁免或删除验证义务。生成旧→新路径/行号/文本映射交 root 单一 owner 机械重绑定；本任务不编辑豁免清单。在重绑定和实际门禁通过前，不宣称 coverage 已通过。

## 最小步骤与恢复

1. 写本计划、保存文档先行证据，再预判 plan。
2. 原样移动 unsupported/identifier 与 Compiler 到私有 compile.rs；sql.rs 只保留现有请求/AST白名单、Prepared 和 prepare 组装；保留原测试入口。
3. 只读比较移动前后完整 prepare 与 Compiler 实现，记录差异/行映射；交 root 独立复核。
4. 等 root 分配资源窗口、准备锁定依赖后运行原始任务范围的全部门禁；修复检查发现需重新复核与验证。不自行提交、推送或创建 PR。

恢复点是上述原始 checkpoint；不存在数据迁移或外部写副作用。失败保留 diff/日志；两次无新证据失败先定位根因，不通过删负例、改预算、关闭 hook 或新增 coverage 豁免换绿。暂停时保留本 worktree 与 receipt，未验证不得 task-finish。

## 验证合同与待验收项

源码准备阶段仅运行标准库 harness task-start/plan 与 diff/文本等价性检查；所有执行门禁均待独占窗口运行。实际风险计划及 required_suites 在源码候选稳定后保存，以 harness 最终选择为准，不因机械拆分跳过必要语言/覆盖率/functional/组件性能/故障门禁。

后续在独占窗口使用现有原 compiler 单元、describe 与 SQL/PG/HTTP 场景验证正例和不支持输入、参数/NULL/int8、类型/顺序/限制/取消错误，并执行实际选中的完整门禁。使用现有固定输入/镜像和预算；不得将文本等价检查写成数据库功能、性能或稳定性通过。无新用户能力，无迁移或可发布声明。

## 结果与独立复核

源码候选已完成机械拆分，root 与 p01_oracles 已分别完成独立静态复核，无阻断。`sql.rs` 为236行，新增私有 `compile.rs` 为188行，`lib.rs` 为200行；Prepared、完整prepare函数及原测试入口逐字保持，移动后的helpers/Compiler仅增加crate内部可见性。describe.rs与原测试文件未改。纯文本等价记录在 `artifacts/query-core-extract/static-comparison.json`，独立复核文本和源码摘要记录在 `independent-review.json`；这些均不是编译或数据库验证。

实际plan选择contracts、functional、harness-tests、performance-smoke、policy、repository、rust、stability-component、unit-coverage共9项，影响query/gateway及INV-001/003/007/008/009/010/011/012。初检窗口已先清除本独立 target 内六个仓库 crate 的复制缓存，保留锁定外部依赖；独立 `.venv` 按三份锁文件安装依赖，`cargo fmt --all -- --check` 通过，无格式或源码改动。`cargo test -p guradb-query --lib --locked` 从当前源码重编译后9项通过，包括原 compiler、describe 及 execution 测试；日志位于 `artifacts/query-core-extract/query-unit.log`。完整门禁与性能/故障/覆盖率仍pending。没有提交、推送或PR动作。

coverage清单的五条原义务全部留在sql.rs，行文本/分类/理由不变：123→103、201→181、204→184、216→196、187→167；完整机械映射在 `artifacts/query-core-extract/coverage-rebind.json`。旧SQL源SHA `7d6753f135345af9470778973129b1df4859892e20a053f1fb4581311ce04f6b`，新SQL源SHA `d6a77508504f358f0d86cf65e7de8b1cb6901a79edf6e134f6145404973d0880`。root 已机械更新共享清单的两处 SQL SHA 与五条行号，p01_oracles 独立确认全15组/21行原豁免义务不变，无新增豁免；清单 SHA 为 `87970d7dab2179e729277e1dc6fa7b3ba63e37226a4e5d61c482c696dd163e76`。后续若源码改变，仍需重新绑定与复核，不能沿用失配摘要。

提交、报告、指纹、checkpoint和PR交付由后续验证闭环记录，不复用其他worktree的通过结论。


## 当前恢复切片（先行合同）

原完整初检 `20261021T011620Z-0add0830` 为FAIL：8/9suite通过，unit-coverage缺Python remote_worker.py第190行；Rust2243/2243、原21排除只属于该旧checkout，不与修后报告拼接。原失败与完整5文件patch8996c69e、旧dirty树/active f55d receipt保留。PR10已修worker测试时序并完成分支、精确main17d及两版本CI闭环；工具修复不改变本片Compiler行为。

在全新 `/Users/chad/dev/guradb-p05-query-core-recovered`、branch `codex/p05-query-core-extract-recovery` 从原checkpoint恢复，先于clean原819上建立 task `f929932ce998427d87782ad6ec676265` / checkpoint `checkpoints/20261021T045455Z-before-p05-query-core-extract-recovery-a9a34e14`，再clean FF到17d66c66。三Rust与旧计划原文的字节/模式已核一致，原基点仍819，不缩成17d。上文9suite为旧阶段，本轮自动plan因完整原始范围实际选10suite；不手工过滤或复用旧计数。

共享coverage-exclusions由root单写，以最新17d清单为底，只对SQL两个既有条目更新当前源SHA和五行位置123→103、201→181、204→184、216→196、187→167；原路径/行文本/category/reason/evidence及其余13组不变，总21行义务不增删。核旧/新源实际行与SHA后保存机械映射；本变更没有新用户行为，不降低100%或增加排除。完成5义务传递与独立复核后旧任务仅abandon并保留现场，新任务完整原819范围重新检查。恢复交接时仅恢复源码，尚未安装本树依赖/target或执行新检查、hook、提交、PR；该时点记录及历史局部结果保留，后续验收见下文。


## 恢复树 INITIAL 验证结果

当前状态：**原始819范围的本地 INITIAL 已通过，提交与交付仍待验收**。新任务 `f929932ce998427d87782ad6ec676265` 保持 active，原基点为 `8198658bc768a96638ad70a12948f3775a5cbab2`。旧任务 `f55d47dea07c4bc99f46847e9475d2a7` 已按接续位置标为 abandoned，旧 dirty 源码、raw、完整 patch 和原失败报告均保留；原报告 `20261021T011620Z-0add0830` SHA `5cb5e9ad6216fb18f61ea62cae8e16ba3ca9c9a424d9d9c14763725c5566b24b` 仍为 FAIL。

本轮使用新树独立 Python3.14.7 `.venv` 和三份依赖锁，执行 `.venv/bin/python scripts/harness.py check --base 8198658bc768a96638ad70a12948f3775a5cbab2`。报告 `artifacts/harness/20261021T051624Z-bd80c193/report.json` SHA `a9040a018b6bc1db62930f40a305edee2c7535ab440d3d96a7f03e1b57a5476b` 实际选择45个变更路径、10suite，26/26命令通过；HEAD 为 `17d66c66a067eebe73280ce8d3488fb4f7cdcfe9`，checkout 为 `d91ef1ddb884948d33965802e6881d89280ff73dc114e69200dd1a7f8f8482c7`，绑定五文件源 manifest SHA `05e171a74d5f544135902f9cfc4abebda298199ba1e909ac1c5028a1b2086eeb` 和本次文字更新前的计划 SHA `3f86898e7191bb13b4a7eafab0237daac56a232df4cf892821b9414de06434fc`。

严格覆盖率为 Python3365/3365、0 missing/0 excluded；Rust raw3344、covered3323、原21行排除，eligible3323/3323、0 missing。完整 contracts、functional、harness-tests、performance-smoke、policy、python、repository、rust、stability-component、unit-coverage 通过。9组阶段 start/finish、源码身份及工具输入摘要匹配；Python阶段21.268秒，Rust189.544秒。仅复制 quiet donor 的普通debug外部依赖缓存，并先通过固定工具链 clean 六个本仓库crate；LLVM目录与计数从本轮新建，未复用旧profiles或报告。OS/服务缓存未受控，该本地结果不提供冷CI时长或产品冷读性能结论。

本轮792份profraw和1份profdata已独立保全并逐文件核对双端SHA；显式828文件 raw清单 `artifacts/query-core-extract-recovery/continuation/raw-preserved-manifest.json` SHA `9b67d1809dbab0e907ddf5718b1fa1cd014b2523a9b1844c0df5948e83ac8902`。Root使用匹配venv独立验证报告、26条argv/log SHA、身份与覆盖率，复核记录 `/Users/chad/dev/guradb/artifacts/reviews/p05-initial/review.json` SHA `e600eec4c3096bde1d8a2ef74c8635a9ea51c0b7ce34d249470464072d24137a`，结论为当前INITIAL通过。

本次结果文字更新改变计划和checkout指纹，以上INITIAL仅绑定更新前的完整候选。正常pre-commit hook、提交后原819完整check、精确新HEAD的task-finish/checkpoint、P05 PR双版本CI及精确主线验收均仍 pending；不沿用该INITIAL作为更新后候选或提交后验收。当前未暂存、未提交、未推送，未建立P05 PR；机械提取也不表示共同读生产P05或I1完成。
