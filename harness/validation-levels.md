# 验证层级 v2（工程工具片，验收状态见下文）

本轮按用户2026-10-21策略修订实施；不是数据库行为/性能门槛变更。原base、失败现场、全部system/release真实命令/预算、strict100与21行有限排除不变。旧报告保留旧语义，不转写成新层级。

`plan/check --level auto|module|pair|system|release [--module NAME ...]`：auto闭集推导；module需要单一owner和真实组件映射；pair需要精确两个端点的已登记真实生产者/消费者profile。未知owner、未登记模块/driver、共享A/API/锁及多owner不在已登记配对中时auto明确fallback system；显式较低层级拒绝。文档只运行cheap checks，不给数据库质量背书。`--scope bootstrap`继续只工程bootstrap，不能task-finish；release仍包含所有planned/missing且失败。

模块strict分母是完整owner生产源（含未导入/新增/删除核对），不只是changed lines，不得遗漏文件或增加豁免。改动Rust profile可调用package范围fmt/clippy/test；Python/Rust源码盘点和测试选择是不同字段，外部依赖可固定fixture，模块自身真实Arrow/DF/S3/PG不能用mock性能代替。现主线尚无新的P02/03/06 driver，registry保持pending，不能标ready。首片可复用现有M0真实native组件驱动及原输入/功能/性能/故障门槛；其证据仅legacy M0，不等于CF1-A/I1。

工程harness变更走真实harness自测/selector差异及代表性query-native回归（工程覆盖若测量则单列；不新增工具源码100%义务）；它没有数据库模块性能或系统/发布声明。独立审查仍是门禁调整的必要交付条件，不由作者自称通过。真实system在主线promotion/集成批次运行；release单独定时/手动，缺失full performance/stability/soak依然missing，不能缩预算或丢命令。

新报告schema2带requested/effective validation level、selected modules/pair/profile IDs、registry/profile SHA、source denominator清单及原selection_base；校验器重算选择与精确argv/log SHA。module报告不能改名冒充system/release，task-finish/checkpoint归档完整claim。schema1报告沿原plan/scope校验，只能写legacy claim。所有报告仍绑定当前commit、whole checkout摘要，运行中源码变化失败；本片不引入旧结果复用或缓存测试结果。

CI保留quality (Python 3.11/3.14)两个job名字。PR与分支push按auto，main promotion显式system；schedule/manual release保留完整义务。工程job预算必须容纳实际ready commands+一次600秒上传余量且≤hosted360min；planned不执行但release必失败，未来ready超限必须拆分而非减工作量。

本页先行合同已落实为工程工具源码；当前有限验收及未通过项见下文。提交/推送仍等ROOT分配窗口与独审，不能据工程结果宣称模块、配对或CI通过。

入口示例（每次必须按实际选择与报告判断通过，不能由映射状态推断结果）：

```sh
python scripts/harness.py plan --path crates/guradb-query/src/sql.rs
python scripts/harness.py check --base ORIGINAL_TASK_BASE --level module --module query
python scripts/harness.py check --base STABLE_BATCH_BASE --level system --batch batch-20261021
python scripts/harness.py check --base all --level release
```

`plan`顶层保留legacy impact，`validation.profile.suites`才是v2实际执行命令；不能把旧`required_suites`当v2结果。CLI/pre-commit默认auto。system包含全部ready和本次触及的planned full-driver义务；后者记录missing而失败。module/pair只在registry声明的Rust改动profile准入；Python等未映射变化明确system，尚未优化。Cargo build.rs有system编译义务，不列runtime分母；非标准Rust path必须完整在owner清单内，生成/跨owner或未知语言拒绝。嵌套build里的生产源码不能被全层忽略规则藏掉。

报告保留fresh命令数/实际命令耗时、wall/log字节及最大串行timeout成本；没有复用结果。profile摘要含实际argv/timeout、registry/architecture、选择/执行/覆盖算法字节与直接命令源输入。task-finish/checkpoint保存原base和具体claim，工程/文档/module/pair通过均不升级为system/release。CI可以手动给固定base与batch排稳定system，定时release的planned缺口仍真实失败。

## 本工具片的实际证据与有限退出

registry的`ready`只表示已有可执行命令映射，允许进入验证；它不表示模块或配对已经认证通过。每次仍须运行完整owner strict100和映射的功能、性能、故障命令，缺行或失败必须保持红色。

原源码冻结`dbf112581450230828159a6027368ce967243068e86196c2cb726e60c66caf54`下，2026-10-21真实bootstrap报告`20261021T134156Z-713b8f5a`通过4条命令，其中harness自测132项、contracts夹具136项。该报告SHA为`7ed44decf79d3a4dee26f3d443957e0df4ce39e86f124fd6e9c498ae08dafd73`，仅有bootstrap claim，不能完成本任务或背书产品质量。

随后唯一一次query/storage scoped strict探针实际失败：Python完整owner分母976/976；Rust可计行710/711，唯一未覆盖行为`crates/guradb-query/src/describe.rs:89`。原21行排除未改，本次仅应用其中属于这两个owner的7行。编译、测试和覆盖导出完成后，strict以退出码1拒绝；首个失败即停止，三个M0模式本窗口执行数为0，module/pair均未认证通过。原失败结果`artifacts/gates-v2/component-once/result.json`的SHA为`86bb16420cf31e063e26ac9ab0bfca962f3baa9b86094cf90d96cfadca729485`；日志、完整分母、LCOV及720个profile原件已保留，不转写为成功报告。

本任务仅交付工程选择、分母、报告绑定及拒绝能力；其退出还须独立复核、正常提交hook的首次完整engineering检查、提交后绑定原base的engineering报告及证据归档。上述strict红项由依赖本工具精确提交的新query-only测试片承接，届时按auto module完整11条命令验证owner100及原3个M0模式；不能在本工具片混入owner测试后仍声称engineering范围。整体模块/配对策略实测、system/release、远端CI与主线合入尚未闭合，现有system/release义务保持原样。
