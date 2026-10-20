# P01 首片：可分发图文 fixture 与独立真值

状态：局部验证、独立复核与首次完整门禁已通过，提交后原始范围复验待归档。归属仅 `tests/fixtures/outline/`、`tests/outline_oracles/`、`tests/contracts/test_outline_oracles.py` 与本页和用户合同；根文档接线由集成者负责。

Git：基点 `169563cf4f0d36e7be8ad6600c941e0139126cf7`，分支 `codex/p01-outline-oracles`，worktree `/Users/chad/dev/guradb-p01-oracles`；起始树干净。task `b9ddc551db914a43b10172ddd5780205`；恢复点 `checkpoints/20261020T232853Z-before-p01-outline-oracles-a2c5463c`。无数据库或外部副作用。

## 验收、范围与不变量

依据 ADR0020、实施计划 P01 首片及训练合同。离线命令能检验固定 manifest、资产/片段/记录版本/特征/边、NULL/full int8、精确检索/图/关系与分组训练样本真值；输入错误有明确负例。首片为 `module-only synthetic`。业务人工相关性、真实模型、框架消费、索引/对象/性能/授权/保留证据不由本片认证；不得将候选预算或源文件字节数冒充产品 baseline。

白名单：中文固定分词、手工 3D squared-L2、全语料统计 BM25(k1=1.2,b=.75)、typed-edge 最多三跳、显式 group/split、一种 query/positive/negative/image 样本。拒绝未知语言/模型/维数、无界图、损坏摘要/坐标、跨版本或跨 split 样本。完整 int8 原始真值独立于 CF1-A wire；适配规范 decimal string/NULL，不另造公共 API。B/C 字段标 fixture-only。

保留逻辑身份与版本、固定 view、唯一事实来源、同组隔离和独立真值不变量；不修改生产代码、门禁、预算阈值或已有 baseline。P00 冻结字段后兼容映射，无循环依赖或生产选择/排名实现导入。

## 先行合同与实现切片

1. 已先写 `docs/user/outline-oracles.md` 与本计划，新增项标待实现；task receipt 固定基点。
2. 创建 CC0 原创 text/SVG 小语料、固定 manifest、手核 golden、负例描述、独立质量与成本预算、对照责任差异。
3. 标准库 oracle 验摘要/版本/坐标/组与 sample；单独计算关系三值逻辑、BM25、精确 L2 与有界图。契约测试以手工公式/成员集合及破坏性 mutation 验证，避免自证。
4. 运行局部测试与仓库计划，交独立复核；正式 harness 与提交使用协调者分配的独占测量窗口。提交后证据必须绑定新 commit，再完成 task。

## 验证合同

- 固定输入/seed/许可/模型/语言和所有输入 SHA-256；无随机下载、生成或运行模型。
- 关系：NULL 的 `=` 结果不通过 WHERE，IS NULL 单独校验；bool 不视为 int8；最小/最大 int8 与超过 JS 安全整数范围逐值保留。
- 检索：全语料 N/avgdl/df，过滤不重算统计；精确距离与稳定身份排序；golden 同时核对版本与 score。无 ANN recall 声明。
- 训练：成员/组/split 显式清单，版本与处理空间固定；重复族不跨 split；缺模态显式排除。人工业务标签为 missing，synthetic 角色标签不替代它。
- 故障：摘要损坏、缺文件、重复 ID、父/成员/模型版本、错误维数、缺图像、跨 split duplicate；每项必须拒绝，fixture 未产生持久/远端副作用。
- 预算：小型离线测试输入固定上限；事实/向量/索引/媒体各自计字节，生产索引与冷热/超缓存工作集、延迟/RSS/GET/训练效益仍 missing。候选阈值不冒充测量值。

## 结果与交接

局部命令已实际执行：`.venv/bin/python -m tests.outline_oracles`、`.venv/bin/python -m unittest tests.contracts.test_outline_oracles -v`（16 tests）、`.venv/bin/python scripts/check_repository.py` 均通过；`.venv/bin/python -m pip check` 无依赖冲突。开发日志在 `artifacts/outline-p01/source-summary.json`、`local-tests.log`，不是正式 harness 报告。

`harness.py plan` 要求 contracts、harness-tests、policy、repository、unit-coverage（含完整 Rust 适用覆盖门槛）；仅测试文件的变化不豁免 unit-coverage，协调者已授予正式独占测量窗口；P00 只允许编辑与轻量单测，直至本片提交后原始范围复验结束。固定 manifest digest 为 `455fc7a3e8c75a1c5446ecc52a3ead105f930607957f8f10eaaca8ffb1d32f94`；事实 24895B、向量 JSON 4169B、synthetic reference posting 2457B、SVG 媒体 846B，原先候选上限保持不变。逻辑坐标以 oracle float64 解释为 240B，未充当生产字节成本。

协调者独立复核已通读 fixture/training/truth、16 项契约测试、预算与对照责任，并实际运行 16 tests 与 diff --check；确认 NULL/full int8、BM25 手核 score、固定版本、分组/重复隔离及 missing 边界，无阻断发现。用户限定后续仅本机模拟云，本片无云服务访问；真实云与多机认证继续未验证。

首次 `.venv/bin/python scripts/harness.py check` 已全绿，报告 `artifacts/harness/20261020T233913Z-f44987e8/report.json`，checkout digest `f929216fad2af890d233481ce395eefd004d6fdd9b023650821f8d6d8697e5d4`，包含全部五项 required suites；Python 生产源码 2968/2968 行，Rust 适用源码行无缺口。该报告对应提交前快照；后续文档记录会由 pre-commit 和提交后原始范围 check 重新校验。最终 commit、精确绑定报告、独立复核和 checkpoint 由 task-finish receipt 归档。未提交前不得标完成；P01 整包还需业务相关性与实际工作集预算校准，首片完成不关闭整包义务。
