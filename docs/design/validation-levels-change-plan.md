# Validation v2：模块/真实配对/系统/发布门禁

## 目标与不变量（先行合同）

按2026-10-21用户原始策略修订，将模块作者默认验证从整库循环改为完整owner源码strict100+模块真实组件，配对、系统、发布证据分开。唯一owner p00_cf1a，本树codex/gates-v2/task972583/原base1e4；ROOT负责全局策略文档，PlanAudit独审代码。无数据库/Cargo/锁/原21排除变化。不能用新层级逃避缺失映射、源文件、案例、性能/故障或提交未知的义务。

## 有限切片及文件域

1. 新`harness/validation.toml`固定profile/实际路径/owner/真实依赖；新scripts/harnesslib/validation.py及按职责registry/report helpers。先做闭集selector与标准库差异/拒绝测试，legacy policy.plan保持语义。
2. scripts/harness.py/runner/check_evidence/workflow/version_control接schema2、CLI及task/checkpoint claim；旧schema1严格兼容不冒充新层级。原所有system/release suite argv/timeout/state保留。
3. unit_coverage/coverage_policy增加完整owner scope：精确Python/Rust source inventory、package和测试集，严格100%，缺文件/空分母/未知模块失败。依赖inventory显式单列，不能因LLVM包含依赖而悄悄缩分母。
4. CI/pr-hook走同一auto选择；主线显式system、manual/schedule release。保留两个Pythonjob名与日志上传、原所有真实driver，不提前接pending P02/03。测试/工具脚本职责拆分每源≤600。

## 初始真实映射与扩散

首片Rust query/storage实际映射现M0功能/性能/故障（真实Arrow/DataFusion/S3及原M0/PGwire输入，不替换原8192×2file×5冷暖或任何负例）。storage→query真实legacy M0配对可登记，明确不是共同A/I1。未有可执行完整mapping的catalog/index/cluster等auto回退system，显式module拒绝。工程域完整selftests/selector负例与差异+query-native代表性回归；工程覆盖如测量单列而不新增工具100%义务，没有数据库性能claim。文档cheap，common/API/依赖锁共享风险system；rename/delete两端及未知owner闭集检测。

## 接口与证据

CLI `--level auto/module/pair/system/release`，module/pair用重复`--module`；不能以选较低level删掉实际owner或共享义务。报告schema2保存selection请求/实际层级/模块/配对/registry和profile SHA/完整source inventory；校验器重算，所有命令精确匹配并核日志。旧scope bootstrap/change/release沿旧义务；bootstrap不可完成任务。task原base不迁移，新claim写receipt/checkpoint。模块通过/配对通过/系统通过/发布缺口分别报告。

## 验证映射/退出

负例：未知owner/未readyprofile/篡改层级或profilehash/只选部分owner/删除或重命名绕过/空分母/漏源/额外LCOV依赖/原21摘要过期/篡改argv或log/运行中变源。正常：docs cheap、query单owner、已登记pair、shared/system、release planned missing不执行，v1 legacy归档。实际selector前后差异保存；标准库small selftest允许，Cargo/服务/正式coverage需ROOT唯一窗口。基线门禁风险由PlanAudit独审，保留代表性真实组件实测；不以源码测试替代真实依赖组件。

先行阶段要求：第一次失败保存日志与具体假设，禁止无依据重试/放宽预算。后续实际运行及有限退出以末段为准。新增层级不提供数据库新功能或发布认证。

独审必要修订：保留7c35原6文件；源码分母采用Git tracked/untracked加owner磁盘闭包校验，嵌套build不忽略；Rust受控path外置源纳入，未认证跨owner/生成路径拒绝。Cargo build.rs属于system编译义务、不是runtime覆盖分母。system=全部ready加本次legacy.required触及planned；修改full performance/stability/soak driver仍missing并失败，不能被fallback过滤。统一binding入口将选择/执行/覆盖逻辑SHA纳入profile并由CLI/validator重算。

源码接入阶段已接CLI/schema2/runner/evidence/task-checkpoint/scoped coverage/CI，当时仅执行标准库工具fixture自测，原数据库功能不变。首次报告用例误预期错误次序、scope用例误比较正则转义字符串的失败均保留；仅修用例为同路径逻辑变更与实际regex匹配，未改生产门槛。后续真实证据见末段，不据小自测宣布本片已验收。

全20源码独审b0fbd79d未见阻断、真实runtime待验；按ROOT已批准的加固仅将profile逻辑闭包扩为固定入口加全部harnesslib Python源，并定义非手工白名单helper变更不能复用旧profile的反例。无原门槛/组件命令/覆盖分母/预算变化。

ROOT有限完整性复核：profile补显式suite_order且v2结果必须同序，v1仍沿旧集合语义；成本wall不能小于串行命令duration之和，容许每命令1ms加10ms舍入差。增加反序与明显零/过小wall拒绝、正常舍入通过用例；仅修协议完整性，不变命令/预算/原工作量。d81c原件已保留，运行待增审。

P01独审指出旧coverage单位临时目录只模拟覆盖数据、不含项目配置；必要夹具适配新增第21文件test_unit_coverage.py，在原四处注入独立字面production_sources catalog，继续验证未导入/缺文件/缺行/rounded totals与失败测试，原断言完全保留。不为生产增加无registry回退，新真实scope/Git闭包测试仍独立覆盖库存路径。此句先于fixture修改；baad20与旧fixture全件已保留。

## 实测观察与工具片退出范围（2026-10-21）

本段及registry注释更新前，完整21文件原件、mode与SHA已保存在`artifacts/gates-v2/finite-engineering-exit-docs/before21/`；原冻结清单为`dbf112581450230828159a6027368ce967243068e86196c2cb726e60c66caf54`。本次仅改两份leaf说明及`validation.toml`的ready注释，选择器、coverage逻辑、测试、argv、预算、排除及模块指纹规则均不改。

真实bootstrap外层退出0、50.765秒，4条命令通过；harness自测132项、contracts夹具136项。报告`artifacts/harness/20261021T134156Z-713b8f5a/report.json` SHA为`7ed44decf79d3a4dee26f3d443957e0df4ce39e86f124fd6e9c498ae08dafd73`，ROOT独审记录为`054db3fac9a9ad239728af5a88ce76edf205c56fa06e1c6b84b926dbb2fb3ae6`。这些是原冻结下的bootstrap工程证据，不能冒充本次说明更新后的fresh报告、正常hook或module/system验收。

随后唯一一次query/storage scoped strict实际退出1：Python9文件976/976，Rust5文件raw718、原排除7、eligible711、covered710，唯一缺行`describe.rs:89`。原21行排除全文未改；native编译、测试与JSON/LCOV导出已执行，summary拒绝缺行后立即停止，没有继续三个M0模式。窗口外层192.390秒，结果SHA`86bb16420cf31e063e26ac9ab0bfca962f3baa9b86094cf90d96cfadca729485`；源21前后相同。720个profile的成员清单与tar在任何下一次Cargo前已保全，原失败报告和raw保持。该窗口的M0执行数为0，module/pair均未认证，不把known red计绿。

ROOT与PlanAudit接受拆成两个有限任务：本工具任务先交付engineering选择、完整owner分母、防伪报告及fail-closed能力；`ready`仅表示命令映射可执行，每次结果仍由strict和真实组件门禁判定。本片还须正常hook首次完整engineering、原base提交后报告、独审及归档，当前hook/提交/post/CI/main均待完成。后续在本工具精确提交HEAD上新建query-only测试任务，仅用有意义的describe正负例闭合owner缺行；保持auto module实际完整11条命令和原3个M0功能/性能/故障出口，不混工具源码、不复制旧失败结果。产品源与工程源混改按现有规则扩大system，此次不改规则来避开它。

这次有限退出不表示整体策略交付完成：模块/真实配对仍待下一片实测，system按稳定批次运行，release planned缺口、原完整命令和原预算仍保持；远端CI与主线合入也不能由本地工程证据替代。
