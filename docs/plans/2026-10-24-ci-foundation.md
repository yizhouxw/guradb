# CI基础执行台账（2026-10-24）

状态：CI-1工程合同文档；后续工程与模块资格均待独立任务实施/验收。本片只写本文件与[harness/ci-cd.md](../../harness/ci-cd.md)，不改变数据库用户行为、源码、机器配置、门禁或远端开关。

来源：[作者#43](https://github.com/yizhouxw/guradb/issues/43)、[CI方案#41](https://github.com/yizhouxw/guradb/issues/41#issuecomment-6384225600)、[架构无环增量](https://github.com/yizhouxw/guradb/issues/22#issuecomment-6384391970)、[产品规划复核](https://github.com/yizhouxw/guradb/issues/25#issuecomment-6384419795)。规划接收不是接口冻结或实现通过；本片[非作者#45](https://github.com/yizhouxw/guradb/issues/45)和[集成#50](https://github.com/yizhouxw/guradb/issues/50)另行接权。

## 可观察交付和支持边界

开发者可从本台账找到当前M/P/S/R入口与pending映射、原始源身份和证据要求，以及不循环的下一步任务/消费者/独审。允许继续现有本机质量入口和不同文档域的接口合同定稿；不因本片合入就开新runner、启用Actions、授予PR准入、把新模块标ready或恢复P05开发。

本片事实基点：`25928a22f17af8434a2dada097b98d2b5313196e`。本地及只读远端main核对绑定该点；未来任务重新记录实际起点，不能沿用本片旧PASS。具体PR/head、分支报告与完成checkpoint以#43实际交付回执为准，不在提交前预填成功。原完整产品、性能、故障、长稳及发布目标保留。

## 当前可用链与尚缺能力

| 类型 | 已有或当前状态 | 验收限制/下一责任 |
| --- | --- | --- |
| 实现：范围与证据 | task原始B、变更/rename两端、owner/DAG、源/profile/配置/执行输入、HEAD/checkout前后绑定，真实argv/timeout/日志SHA、task-finish/checkpoint归档 | 哈希/结构不证明driver语义或审查者身份；raw、外部副作用与备份另核 |
| 实现：M/P选择 | query/storage仅`.rs` ready，legacy-m0 component与storage-query pair | ready仅表示可尝试执行；Python及其余owner独立映射pending，未知/过窄请求按实际system/reject，不等于新CF1-A链认证 |
| 实现：覆盖 | 完整owner、未导入Python纳入；Python80%、Rust适用行100%，整数判定/非零分母，Python零排除、Rust原21行不扩 | 当前scoped profile仍要求两种语言均存在，纯Rust适配未实现；无语言须核全部源后明确N/A，不能0/0 PASS |
| 实现：组件driver | 现有PG/P03/P04/P06等受限驱动可读、可复用相应输入与实现 | 不自动给新Rust package或消费者profile资格；旧S通过不能替代新route真实driver |
| 人工：协同与资源 | PM核唯一DRI/文件权/四槽、非作者独审；ROOT串行main集成 | Issue事件不自动调度；worktree/receipt、coverage锁不提供跨树/宿主资源锁；重测/coverage/性能/迁移/main需唯一窗口 |
| 拟补：工程 | 独立target/计数器/缓存、远端B/H/checkout/M/G/attempt绑定、模块内接口→真实consumer扩散、逐模块语言/driver接线 | 由CI-2/3/4A/4B独立实施与独审，不在本片宣称能力完成 |

现有Cargo workspace只有common/storage/catalog/connectors/query/gateway六包；逻辑index/cluster等不据名称自动成为已存在Rust package。[architecture.toml](../../harness/architecture.toml)声明owner/DAG，不能代替实际Cargo/driver。未知owner、共享API/锁/迁移仍按现有[selector](../../harness/validation.toml)保守扩大。

## 分层执行与身份交接

按[开发流程](../../harness/development-workflow.md)建立独占`codex/<issue>-<slice>`树与receipt，固定原始`B`；安装三份requirements锁，用`plan --base B --level auto`读取实际`validation.profile`。本片仅documentation四suite，不运行产品coverage、性能或容器，不宣称M/P/S/R通过。

| 层 | 命令示例（在`python scripts/harness.py`后） | 必需结果与消费者 |
| --- | --- | --- |
| M | `check --base B --level module --module query` | 已登记映射的完整owner源码/实际语言与自身真实依赖、独立真值/拒绝/原功能性能故障；模块消费者签收，不只看改动行 |
| P | `check --base B --level pair --module storage --module query` | 当前旧pair仅legacy-m0；新pair须真实两端、固定同view/ID/version、授权、预算/取消、unknown/清理/恢复及独立oracle |
| S | `check --base M --level system --batch ID` | 唯一集成窗的稳定main候选，完整M→G和新增route必需真实驱动；保留原39命令适用义务，旧driver不能补写新route PASS |
| R | `check --base all --level release` | 发布候选完整环境/性能/fault/soak/升级恢复；目前三项planned仍missing/FAIL，不因CI基础清账 |

`B/H/M/G/ID`替换为实际完整SHA/批次。正常hook后在干净H按原始B做post-check、task-finish/checkpoint；非作者绑定同H，H更新后重核。集成者核最新M和依赖，以expected H执行merge commit，在独立干净树验证实际G、归档checkpoint并确认远端main。PR合成checkout SHA与H、预览merge SHA与实际G分开，CI当前base不替代作者原始B。文档报告只支持documentation claim。

## 环境、容量和开关分线

| 决定 | CI-1当前边界 | 后续解除物 |
| --- | --- | --- |
| 现有本地执行 | 继续现有环境，正常本地门禁/独审/主线证据；不采购或注册runner | 各有限工程任务自己的精确报告，不把本合同文档当CI代码已落实 |
| 独立worker候选 | Linux专用worker或hosted短M/P＋专用S/R仅候选 | 用户确认环境/预算/运维owner、可信执行范围、隔离、网络/S3/取消/证据与容量实测 |
| Quality Actions触发 | 政策保持`PAUSED_BY_USER/NOT_RUN`；historical diagnosis不自动恢复 | 用户另行授权特定PR/main/manual/schedule触发，先真实候选成功/失败/取消/缺证据验证 |
| PR required contexts | 与恢复Actions独立，当前不设远端CI准入 | 管理员读有效规则、稳定唯一context和真实结果，再按单独授权设置；独审和禁止强推保持 |

本片未读远端管理API：实时workflow开关、活动run、runner注册、套餐/配额、保护规则均unknown。`ci-state.json`只是政策决定，之前disabled快照不是当前远端事实。CD/部署、账户/权限/无关保护不在本片授权中。

当前[policy](../../harness/policy.toml)10个ready suite、39条命令的**串行timeout合同**合计21120秒，加原600秒证据上传余量=21720秒=362分钟，尚无setup成本；不是实测耗时，setup未知。保留YAML普通340/release360分钟均不满足该合同，两个容量测试在暂停时SKIP不算PASS。恢复前不得缩timeout/负载/源分母、只调开关或以旧结果补绿；具体环境与必要有限分job证据协议由CI-3承接，不建通用分片/union工具。

## 有限任务与唯一写权

下表是规划候选，不代替正式成员Issue或派发。PM逐项查重、登记完整DRI/消费者签收/精确路径/独审Issue、绝对检查时间与资源窗后才可执行。E=集成/工程`01a16109-3476-7532-8d46-7762c1fea2b3`；A=架构；T=专职非作者系统测试；各模块开发DRI按正式Issue登记。同账号只记录真实COMMENT，不伪造Approval。

| 任务与唯一作者 | 精确候选文件域（派发时冻结子集） | 输入→交付/消费者；非作者验收 |
| --- | --- | --- |
| CI-1／E，本片 | `harness/ci-cd.md`、本文件 | 无运行时接口前置→本地分层/状态/容量/后续无环台账；#45独审，#50集成；实际documentation plan/check、正常hook、原B post/receipt/checkpoint/真实PR |
| CI-2／E，隔离/缓存 | `scripts/cargo.py`、`scripts/unit_coverage.py`、`tools/m0/Dockerfile`、`tools/test-coverage/Dockerfile`、`tests/harness/test_unit_coverage.py`、`tests/harness/test_unit_coverage_phases.py`、`tests/harness/test_runner.py` | CI-1及选定本地执行边界→独立target/run-dir/镜像与计数、不串覆盖、只清本run；所有M/P消费者。T审；现有拒绝/取消负例、有界双树竞争与实际engineering/system检查 |
| CI-3／E，身份/容量/证据 | `.github/workflows/check.yml`、`tests/harness/test_ci_workflow.py`、`scripts/harnesslib/runner.py`、`scripts/harnesslib/check_evidence.py`、`scripts/harnesslib/validation_binding.py` | CI-1→B/H/checkout/M/G/attempt、每job容量和上传允许清单/脱敏；恢复候选消费者。T审；错head/缺片/取消/日志缺失拒绝、实际plan check。配置可改但Actions保持disabled；若分job先审有限闭包，不删原义务 |
| CI-4A／E，通用接线 | `scripts/harnesslib/validation.py`、`validation_registry.py`、`validation_binding.py`、`scripts/coverage_scope.py`、`harness/validation.toml`、`tests/harness/test_validation_levels.py`、`tests/harness/test_validation_reports.py`、`tests/harness/test_coverage_scope.py` | CI-2、冻结接口/QA-0的实际输入→语言完整源/consumer与拒绝逻辑可消费；模块作者消费者。T审；新增/删除/rename/未导入/忽略/过窄/缺语言负例及实际plan。无包/driver的owner继续pending，**不要求首M先通过** |
| M-source(m)／对应模块唯一开发DRI | 该模块`src/`、`tests/`或正式Issue专属fixture精确文件，不写共享workspace/锁 | 4A框架及对应已合入签收合同/必要类型→真实源码、driver/测试候选；E/T消费者。非作者独审；未有可执行profile时实际system/reject，加新真实driver，旧S不替代新route；缺证据保持WIP/HOLD |
| BUILD-K／E | `Cargo.toml`、`Cargo.lock`、`crates/guradb-cluster/Cargo.toml` | K实际源码/依赖feature delta、冻结接口/组合点→可编译构建身份；K/4B消费者。A审依赖、T核范围/真实构建报告；不造空包，不称模块或覆盖通过 |
| BUILD-X／E | `Cargo.toml`、`Cargo.lock`、`crates/guradb-index/Cargo.toml` | X实际源码/依赖feature delta、对应artifact合同→构建身份；X/4B消费者。与BUILD-K串行，A审、T核证据；不能合法独立验收时明确串行交权与有限候选收口，不绕hook拆假绿 |
| CI-4B(m)／E | `harness/validation.toml`、`tests/harness/test_validation_levels.py`、`tests/harness/test_coverage_scope.py`；模块生产域只读 | 实际package/driver/源码候选、必要BUILD→**注册候选**；T独审后执行首个完整owner M，成功才登记该模块实测资格。模块作者同步后用实际新H/原始B再验结项；其余pending。注册前不要求尚不能执行的M已PASS |
| CI-7／E，可选恢复试点 | 未来另授权的workflow触发/开关、`ci-state.json`及有限ADR；不含本片 | CI-3、选定环境、真实M/P/S候选、用户明确授权→实跑成功/失败/取消/缺证据及资源清理；T审，PM/用户消费者。PR准入另一步，不改无关保护 |

当前IF-R0另由架构在[模块合同](../design/module-delivery-contracts.md)文档域定稿/直接消费者签收；IF-R1实现必要common类型，后端只消费已合入版本。QA-0独立oracle/预期/输入映射只依赖对应冻结接口及现有CI证据合同；其fixture自检不表示Rust真实端或P已通过。具体生产任务/目录/方法以接口定稿和正式Issue为准，本台账不授予模块写权。

无环阶段顺序：

```text
CI-1 ∥ IF-R0合同定稿/消费者签收
IF-R0 → IF-R1必要类型；冻结接口 + 现有CI合同 → QA-0
CI-2 + 对应冻结接口/QA-0输入 → CI-4A框架
CI-4A + 已合入必要接口/类型 → M-source真实候选
M-source(K/X) + 精确依赖delta → E的BUILD-K/X
真实package/driver候选 + 必要BUILD → CI-4B(m)注册候选
注册候选 → 首个完整owner真实M/资格 → 作者新H原B结项 → 真实P → 串行main/S
```

CI-3可与接口定稿分时推进，但CI-2/3/4A/BUILD-K/BUILD-X/4B全在E队列串行，不因图有分叉就同时授相同文件/资源。CI-4B不是写源码候选的前置，首M也不是4A/4B注册候选的前置；注册声明ready≠实测资格通过。新包无法在当前ready校验中登记时保持pending，不用空Python或0/0凑分母。

## 资源、失败与交付纪律

各工程片落实独立venv、target/coverage计数、run-dir、端口、PG实例/库、对象前缀和镜像ID；当前未实现部分人工排窗。下载缓存键包含OS/arch/Python ABI、三份requirements锁、toolchain/Cargo.lock/Dockerfile摘要；构建缓存再绑profile/参数/源码。写缓存唯一owner，不缓存PASS或复用计数器，性能冷热分线且保原质量/成本。

PM保持四槽：最多两个行为作者，T独审/验收，A/E按需要分时；文件写权与重资源窗口另核，不把4个会话当4套独立机器。接口变化扩真实consumer闭包，未知映射仍system/reject。稳定点及时交下一消费者，进度按已验收M、真实P、精确main/S分别计，记录阻塞owner、等待集成、验证耗时、首次通过率，R未通过不清账。

失败日志、diff、raw和旧报告保留；网络/S3每独立阻塞先用20分钟排障时间盒，或同条件两次无新证据失败即停盲试，交PM列owner/根因/下一动作，不增通用诊断工具、不改driver原timeout。按[恢复合同](../../harness/version-control.md)从checkpoint到新目录，原现场不reset/clean/stash；修复/revert仍PR，代码回退不撤销PG/对象/迁移副作用。

本片完成标准是两文件实际diff、documentation检查/正常hook、干净H对原B复验、作者receipt/checkpoint与真实PR，再由#45独审及#50精确main验收。只此合同完成不能宣称CI-2/3/4、模块或数据库产品已支持；原P05候选覆盖670缺行仍HOLD，完整performance/stability/soak/release义务保留。
