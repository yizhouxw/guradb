# Query owner：Describe 数字参数推断测试

## 范围与先行合同

本任务是内部测试补证，无用户可见行为变化。唯一代码变更为在现有`crates/guradb-query/tests/unit/describe_existing.rs`追加两个真实Describe正负用例；原五例、原断言和生产源码原样保留，不改SQL语法、参数类型、错误分类、lib入口、覆盖排除、harness或预算。因此不修改用户操作手册，也不将测试新增描述成新产品能力。

本树`codex/query-owner-inference-tests`，task`7c8222175e9b48c187c7d1f174032a66`，原始base固定为工具提交`82b2bfeeac6fd1186ce33f644e0d38fc4dd263cc`。该工具片提供可执行的module选择与严格owner分母；`ready`不表示模块已认证。此前工具树唯一scoped探针实际失败，query的`describe.rs:89`未被自身测试覆盖；原失败报告、分母、LCOV与profile永久保留，不挪用为本任务通过。

修改前已保存原完整测试文件、SHA/mode与五例数量到`artifacts/query-owner-inference-tests/source-first/`。本先行说明先落盘，再原样追加P01候选`c1c38e420c035758c9f93a3e08bd73d9fe020dcbba96cd396605f1427a6abb5b`；该候选已由ROOT独立源码复核`00d1a01a`，源码审查不等于运行结果。

## 行为与独立断言

正例从现有公开`describe`入口进入，复用不可读的`/nonexistent` source fixture，不调用私有`infer`填覆盖。非负数字零和int8最大值参与占位符比较，必须推断两个`int8`参数，并按既有Column序列化边界核对投影结果。Describe无需读取源数据；测试不能改用真实可读数据来掩盖其元数据路径。

负例继续经过同一公开入口和唯一执行Compiler：同一占位符被数字及文本约束必须明确`invalid_parameter`，正数超int8字面量必须保持原`unsupported`拒绝。不修改expected来迁就新门禁，不引入第二解析器或借用gateway用例替代query自身用例。

## 验证与退出

预期auto选择单query owner的module profile：原四条廉价检查、真实query fmt/clippy/test、完整query Python/Rust owner strict100及原M0功能/性能/故障，共11条实际命令。分母包含query完整生产源而非新增测试行或changed lines；依赖组件仍真实执行Arrow/DataFusion/Parquet/S3/PG wire，不以fixture测试替代。原21行排除保留，适用owner条目仍按原源码指纹严格校验。

M0性能仍为原8192行、两个文件、五个新进程各cold/warm一次，逐次结果真值、对象计数/字节、10秒与512MiB门槛不变。功能与故障保留现有全部查询/负例、撤权/取消/超时/恢复输入，不缩成只测新Describe语句。M0通过也仅认证legacy组件白名单，不表示CF1-A/I1、完整系统或发布通过。

本轮只SOURCE与实际plan，不运行格式器、单独测试、Cargo或服务。待源码冻结独审及ROOT授权后，仅对该测试leaf格式化，再通过正常commit hook执行首次完整module检查，提交后绑定本任务原base做一次必要报告；不先额外重复同一整套check。首失败保留输入、日志、源码和profile，先定位再按授权处理，不自动重跑、跳门禁或改阈值。

当前实现、格式、运行、strict100、三个M0模式、hook/提交后报告、独审归档及远端CI/main均待证实；CI账户阻塞不能由本地通过豁免。两个测试只在后续实际执行并核对结果后才可记为通过，整体分层策略交付仍有后续模块/真实配对/系统与发布义务。
