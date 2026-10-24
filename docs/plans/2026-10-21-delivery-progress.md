# 实施事实账本

2026-10-22本地C1/D1派发快照；上一17:13实测快照保存在`d48a645`。2026-10-21 17:13:09 UTC B2独立实物通过 / P05新组件首次实测检查点（P05非作者实物复核c3dc2e9d通过）；15:25快照保存在8823331。执行[策略 v2](2026-10-21-modular-delivery-v2.md)，需求见[矩阵](../product/requirements-v2.md)，机器度量见[JSON](2026-10-21-delivery-metrics.json)。14:43 快照保存在前一 commit；本页按新源码/实际命令续记，旧失败原件保留。合同、模块、真实配对与主线用户能力分别验收。

## 已验出口与真实链路

| 功能面 | 实际证据与本轮结果 | 当前出口与缺口 |
| --- | --- | --- |
| CF1-A / 独立真值 | 主线既有12 golden/23拒绝双语互通、P01全11成员；唯一Rust SQL core已合 `1e4f6a6` | 合同/核心实物，不是新 PG→对象→SQL 用户链；人工相关性/业务数据仍缺 |
| P02固定目录 | `86fcaf0`；原4d基点，正常hook/clean post均10suite/29命令，六轮真实PG，独审de26d633；task b826完成、checkpoint125543…b6e71f7f | [PR14](https://github.com/yizhouxw/guradb/pull/14)分支已验；真实PG父控制→读取、CI/main待闭合 |
| P03固定对象读取 | 新44源 `2d1dfa7d`：34纯单元+26socket/存储单元，以及原12功能/4性能/12故障全部实际通过。真实窗口50.131s，ROOT释放5ad7d23c、p01独审0c05f60e | 只读组件稳定，已用于A真实配对；新task476c1的原4d strict/full、正常提交/PR仍待完成。SDK写入诊断原LIST7/预期8 FAIL、旧PR13失败保留，未改期望 |
| P03→P04真实配对 A | 新28源 `51601127`：44单元，真实Seaweed/S3→固定对象→窄Parquet→ReadBatch；原6功能/4性能/23故障通过。3CLI分别17.743/16.660/5.620s；314许可证据/3.319MB，ROOT逐原件复核fdd9a13e | 本地**单SourceVersion组件配对**通过；原receipt4696/base17d的strict/full/提交尚未完成，p01实物独审ef3e107e。不是多Source、真实PG/Rust、主线或I1 |
| P04 B2私有located | source33 `a509e6e2`：FIRST79内1.150s/外1.400s；原功能10+located4、性能8+located4、故障26+2均首次通过，24.242/17.182/5.993s；532安全原件、release cb0b8b4e | 同父账A+P≤768KiB及真实PyArrow定位组件/P03配对；p01独立实物审6f5b29dc通过。无P06/PG/Rust/I1或strict/full/main结论 |
| P05 Rust固定查询 | 新31源 `c32f44b6`：R2完整Value预约与NULL fixture修复后，首次完整 `cargo test --package guradb-query --lib --locked` 55/55，0过滤/忽略，外16.612s；p01实物独审8e51f46b | 真Arrow/DF及全11行/8192源行32批的lib测试已运行；fixture provider对象IO为0。新sealed-fixture Arrow/DF组件已有下方首次性能实测；generic Source/PG/bridge、native硬界、全fault、strict/full和I1仍缺，不借旧M0报告代验 |
| P06固定索引 | 历史真实BM25/精确L2产物与独立数学/定位真值 | 100行/单shard/1MiB；多Source/真实父账、Source→Index→Query回表未接；ANN/Graph另需求 |
| 正式用户纵向结果 | **新 S-SCAN、I1/I2/I3 均待验**；legacy alpha保持原能力边界 | A不能替代完整PG绑定/两来源/Rust/正式HTTP与PG同facade；I1还含BM25/精确向量，扫描成功也不可改称I1 |
| PG物理直写研究 | 官方Lakebase物理bulk、Neon WAL/page、逻辑COPY已分立B01–B05；PG18.6/aarch64原语34命令/3.714s，12行读回与3个SQLSTATE实测，ROOT独审049cbb98 | 只证明stock PG格式原语；目标原生extension/API、物理兼容与恢复仍missing，不以wire/COPY冒充 |
| 策略、需求和合同 | 19文档/42需求、唯一owner/交接、Rust/Python权威和迁移条件，非作者产品/架构复核；`0981fc3`及`6a56e54`两片已完成正常hook/post；后片完整PR原1e4的19路径检查424acb7a通过 | [PR15](https://github.com/yizhouxw/guradb/pull/15)已推送，本轮仅续记事实/排程；文档不计新增数据库行为，CI/main待闭合 |
| 分层门禁 | 21文件 `82b2bfe`，engineering正常hook/post各5/5，每轮132 harness/136合同及query-lib9；task972583完成、独审/ROOT核验21d91c1d | [PR16](https://github.com/yizhouxw/guradb/pull/16)待CI/main；初始映射仅Rust query/storage+legacy-M0，Python/shared/未知映射仍扩到system，不假称全部模块已优化 |
| query既有行为补测 | `ad5c9fe`正常提交（含hook）外层557.170s、clean原82基点post418.634s，均9suite/11命令；完整12生产源Python890/890、Rust623原始−5原owner排除=618/618，原全局21排除不变。两轮共6个真实legacy-M0 driver通过，p01独审540f7fbb | task7c822完成、checkpoint150138…95f886d2；[Draft PR17](https://github.com/yizhouxw/guradb/pull/17)正常推送并依赖PR16。属测试投入，没有新增用户功能，也不认证P05/CF1-A/I1 |

P04实际fixture认证包含固定镜像请求和Docker实测ID/platform、SDK三版本与模块SHA、真实 `Config.proxies={}`；未认证镜像config digest等价性或SDK客户端独立close。生产对象读仍由原P03传输承担。P03/P04原性能规模、取消/期限、失败计费和缓存上限未降，源码在运行前后匹配；本次普通单元可并行，真实性能窗口独占。

15:18 fetch确认origin/main仍为 `1e4f6a6c26eb28982f4b61cc75aa05e290211809`。15:17 REST在PR14/15/16/17最新head核对，8个Python3.11/3.14作业均因付款或支出额度问题未启动，步骤数0。快照099b49b1保留；没有远端测试通过，也没有合入。ROOT已将账户动作交给用户，继续本地交付，未改账户、远端设置或合入条件。

## 关键路径、等待与唯一负责人

| 剩余出口 | 唯一负责人 | 当前阻塞与解除动作 |
| --- | --- | --- |
| CI及主线集成 | ROOT集成；用户管理账户 | PR15/16及其依赖PR17、P02等候选按依赖串行；解锁后读实际CI，再做合并后system/checkpoint。等待不能全归因CI，真实消费者仍有接口缺口 |
| P03/P04分支完整出口 | plan_audit实现；ROOT/p01非作者审 | 新组件与A已验，原始receipt范围保留；门禁映射未进入这些旧基点，strict/full/hook/post尚未做，不缩base或复用历史绿冒充fresh |
| B2：显式located出口 | plan_audit | B1实际main10+mirror1与双源130已独审通过；B2首次79与三CLI通过并获独立实物审6f5b29dc，源码冻结，原父账及普通A不重开；P06消费者仍缺 |
| P05新M1模块出口 | plan_audit（D1临时DRI） | cooperative sealed-fixture真实Arrow/DF probe首次通过，5进程cold/warm共10性能样本；非作者实物审c3dc2e9d通过。generic Source/PG、native硬界、全fault、strict/full仍缺，legacy-M0不代验 |
| C：真实PG父控制→读取 | ROOT装配；接口由原模块owner供应 | catalog受控调用与storage/source父控制接入口缺；PG网络reauth不能塞进仅认证内存callback。实际暂停PG/撤权/对象故障须验证同父期限/取消/lease清理 |
| D：真实Source→Rust | ROOT组合；query owner实现消费者 | B+C+P05模块稳定后接有界bridge；禁止以SealedFixture的0对象IO包装真实源。保留全11成员、失败attempt已知性、背压/取消/kill-wait-reap |
| E/F：索引回表与正式入口 | p00负责E；ROOT负责F | E接B/C located及真实跨attempt父账，再由D回表；F正式HTTP/PG只调用同一Rust facade，先S-SCAN再补完整I1 |
| PG物理目标原型 | connectors DRI；p01研究 | 缺目标原生extension/API及版本兼容合同；隔离stock PG原语已验，不阻塞对象湖scan，不伪造物理写入接口 |

A的稳定交接从P03 ROOT释放14:57:38到P04首功能命令15:18:34约20.9分钟；15:20确认资源回基线。这个时间只说明局部模块稳定后尽早配对，不认证全模块/M→S。P02从12:55:43 task-finish至15:25历史快照约149分钟；历史16:34快照约218.6分钟仍未main集成，精确分钟见JSON；其中也有接口等待，不能全部归因账户。

四个实际槽位：ROOT负责PM/共享/组合与事实；p01产品及独立测试/文档审查；plan_audit临时接query D1唯一DRI、storage/connectors保持冻结；p00接catalog C1。该派发时为两项行为实现；恢复时旧agent全部停止，新C3审查与D2接口方案并行，行为写入暂为0。旧P03/P04/P06/P08现场与原receipt保留，不同时派发其它行为写入；方案、测试与文档不冒充新增用户能力。

## 验证成本、首次结果和工程优化

P02原完整窗口1404.400s，hook724.422s/post673.946s，六PG driver约80.033s。它与新模块范围不同，不能直接宣称加速比。工具engineering hook/post121.933/114.521s也只认证工程工具。原strict探针192.390s实际Rust710/711失败、三个M0未执行，红项与profiles保留；query补两例后在新精确源码上完成整模块，不改100%或排除。

P03新组件纯34单元4.039s，另26socket+三原driver50.131s；P04复用已核三锁的现有matching venv，不重建环境，44单元0.778s，三driver合计40.023s；P05首次native编译14.85s、test1.49s。组件等待与验证耗时分别计，不以快速lib测试代替新M1性能。此前P03诊断失败29.131s、镜像预检与PG引用解析失败继续单列。

query两轮coverage原件用一次遍历清单/归档，外层各约0.65/0.67s，profile与tar保留；独审明确只流读post native一次，不反复扫描历史bulk。已定位的重复编译与夹具启动/清理成本仍须分段证据，下一工程小片只给原命令加有界阶段/dirty原因观测，不先改cache、规模或阈值。Python模块ready映射需随真实组件及完整owner分母单独交付，不能由现有Rust映射推定。

全历史功能首次通过率仍未知；新query测试小片首完整模块1/1、P05首native/lib阶段1/1、A当前fixed-source候选三driver首轮1/1分别记账，后两者不计完整模块/新用户功能首次通过率。Rust行为、公共合同、测试、工程工具四栏独立统计，不用文件/行数计算产品百分比。本机模拟云只覆盖同一物理故障域；真实三机、云认证、HA/PITR、完整performance/stability/soak与发布仍缺。

| 包 | 当前状态 / 下一实物依赖 |
| --- | --- |
| P00 | CF1-A/1.0首片经PR#9合入4d6baca，精确主线10项门禁、12golden/23拒绝码双向互通、两版本PR/主线CI闭合；B/C仍待下游反馈与独立验收 |
| P01 | synthetic图文/组真值首片已合入84c07af2并完成本地/远端主线验收；业务样本/人工相关性、真实模型/框架及生产规模预算未完成 |
| P02 | 新恢复树运行前2432清单已通过26targeted、232Python/4028行零排除和PG七容量performance组件，独立实际4516文件/4509正文及语义复核PASS；完整原4d门禁、Rust、新functional/fault及提交/PR/main仍pending；保护fixture与I1/HA边界保持 |
| P03 | 固定ObjectRef本机读取恢复树已通过原4d完整INITIAL九项门禁（232项Python/3804行零排除、Rust3323行与原21行豁免、真实三driver），报告0e436457及作者外复核；结果文档更新后的正常hook/提交后原范围检查、PR与精确main验证待完成，PG/P04/I1未接通 |
| P04 | 待P03/CF1-A/P01，先固定源ReadBatch；生命周期部分依赖B |
| P05 | 待CF1-A/P01，先共同请求/关系/精确计划；训练选择依赖C |
| P06 | 待CF1-A/P01，先固定revision产物与覆盖证明 |
| P07 | 待P02交权及CF1-B，持久Job/Pin/源回执/GC |
| P08 | 待CF1-A/P02/P05，正式登记/查询入口；媒体/导入依赖B |
| P09 | 待CF1-C/P04/P05/P07，真实框架多worker/尾批消费 |
| P10 | 待P03–P06，按需provider/真实算子/媒体批回表 |
| P11 | 待CF1-B/P03/P04/P06/P07/P08，源提交与刷新编排 |
| P12 | 待CF1-A/P03，最小安装/观测可提前；正式接线在P13 |
| P13 | 待共同读子片，按I1→I2→I3串行接线；G1未开始验收 |
| P14 | 待接口冻结可做driver，正式质量/成本测量须P13候选 |
| P15 | 待P14及获准三台独立环境；G3前必须P17a真实接线 |
| P16 | 待P15/P14/P17a，完整M3集成 |
| P17a | 待CF1-A及P03/P08身份/凭据合同，远程身份/传输 |
| P17b | 待选定首云/P15/P17a/P03/P08及测试账户/预算；尚无云认证证据 |
| P18 | 待P07/P11/P12/P15接口及PG主备/WAL/隔离恢复环境 |
| P19 | 待真实候选与环境，完整性能/故障/长稳；不得用组件门禁代替 |
| P20 | 待P16/P17a/P17b/P18/P19，全部G5/M4义务及独立复核后才可发布 |

<!-- PR15 原始策略/历史事实补充；当前事实以本页最新集成记录为准。 -->
下一可观察用户结果仍是主线上可复现的正式S-SCAN，随后完整I1，再图文更新I2及实际训练I3。当前A和55lib是向该结果前进的实际证据，尚不能把用户结果标完成。

## 16:34 UTC 双源配对与工程增量

B1 source30 `0de215b4`：65单元内0.706s/外0.973s；实际功能10/24.032s、性能8/18.914s、故障26/5.884s通过。p01独审e8a78f02核14实际Parquet、52原始ReadBatch/replay、34页与59故障对象；全11来源/值/物理定位、双源130的64/64/2和同父账吻合。最大page38.964ms/cohort58.985ms、取消7.024ms，原cap不变。此为本地组件与P03真实配对，不认证strict/full/PG/Rust/B2/P06/main/I1。

P00首次完整检查记录在其worktree的`artifacts/harness/20261021T001010Z-2bffa650/`。历史Rust Clippy的`int_plus_one`与`large_enum_variant`诊断已修复，失败现场保留；该失败报告没有用于通过结论。修后独立复核、重新编译、互通、覆盖率与完整门禁以及PR/主线交付均已另行完成，精确证据如下。

P03任务为`653a8ca54b7845ccb03ecf777afbaf36`，分支`codex/p03-fixed-objects`，目录`/Users/chad/dev/guradb-p03-fixed-objects`，原始base为4d6baca，checkpoint为`checkpoints/20261021T015433Z-before-p03-fixed-objects-dd387582`。p01_oracles独占storage fixed_*、对应unit/support与driver/三份先行文档；root在明确交权后串行接用户导航、此追踪与harness/architecture/policy及防漏选测试。R1修订的19文件清单SHA为`aa42b5f1b7a34adb560764ca889338179c9de53899109d65828ca04dc8738d3b`；root已实际读源码与新负例并重算全部摘要。旧18项单元只绑定历史SHA。后续telemetry候选25文件清单7fd121054724d2697997b9b88958e6204a9ed616bdf14254d5d441063237b97c已重新验收26项单元、230项Python测试/3804行零排除及三种真实本机driver，精确报告SHA/路径见[变更计划](../design/fixed-objects-change-plan.md)，root已独立读原始记录并核验。以上为旧树历史局部证据；恢复树后续已重新完成原4d范围INITIAL九项门禁，精确结果见本页末段，不能把旧checkout或本轮更新后的文档SHA当新检查通过。

<!-- PR15 原始策略/历史事实补充；当前事实以本页最新集成记录为准。 -->
首轮65内0.726s/外1.117s有1个新增oracle错误，三个CLI未启动；窄修只注入确定时钟并加强1ms期限收紧，原44与21定义/生产/预算不变。修后3CLI首次实际执行全通过，外层52.139s仍因索引漏列既有.bin而FAIL。只按26个objects.json补精确59bin/450文件7.040MB索引353223d5、独立释放4b543，未重跑已过组件/未改原FAIL。系统default bridge ID变化原因未证，containers为0/volumes同基线/自有PID均退出，不清理未知资源。

工程PR16已续至`23a2e37`，完整22文件：main-only push去重、2个触发正负例、PR auto/main system/manual/schedule/release保留。normal hook116.937s、own-base post40.996s，5/5且134 harness/136合同/native9；额外整PR范围检查41.042s，非作者独审6a45a55e。native编译行56/0/0只是观测，根因/全局提速未证。PR15前片已结项至8823331；15:54最新PR15/16 run仍0步骤计费失败，未合入，16:10:57 fetch主线1e4。

CF1-A [PR#9](https://github.com/yizhouxw/guradb/pull/9) head为`e0abf74728e8797133268a3ab020c4369dc36f6e`，合并前main为`8198658bc768a96638ad70a12948f3775a5cbab2`，merge为`4d6baca888421d90f146679ef71b0e555fe60881`。精确主线报告`artifacts/harness/20261021T013721Z-42424eaa/report.json`的10项/26命令全通过，报告SHA为`1ac66d36a01bb586e309d38ae31d5718e164cc5d863f1a6e7d8553213b4a0225`，checkout为`1695dea8b5192f908521aa42ebffa14d6113acbefa1bc0f45f4ca4a74bc4ef35`；checkpoint为`checkpoints/20261021T015015Z-p00-cf1a-main-verified-5ce1adab`。真实跨语言互通重新编译运行，raw archive位于共同Git的`guradb/roundtrip/5ef9a7e666765046be75ee59f7f553d7abbc4f99f0ac7cd5a08736987f5a421e`；[PR CI](https://github.com/yizhouxw/guradb/actions/runs/39525801267)和[精确主线push CI](https://github.com/yizhouxw/guradb/actions/runs/39528308712)的Python3.11/3.14均success。此片仅为离线合同，不证明PG/对象/源/索引已真实接线。

| 交付 | 精确代码、检查与恢复证据 | 已验证边界 / 未完成项 |
| --- | --- | --- |
| 进度入口[PR#6](https://github.com/yizhouxw/guradb/pull/6) | head `196471920b4d62b05c423a4cddf7bad4d76a2cfb`；merge `ad68168a3f397ce42cb13415204f23b1962024dd`；分支receipt `22a4a985d3cf4ce887a058f37c23d1f7`；主线报告 `artifacts/harness/20261020T233518Z-cbc9e706/report.json`，checkpoint `checkpoints/20261020T233616Z-delivery-progress-main-verified-8b365ecf` | plan_audit独立复核、文档四项门禁及两版本PR/主线CI通过；仅计划状态，不新增运行时 |
| synthetic样板与独立真值[PR#7](https://github.com/yizhouxw/guradb/pull/7) | 原始base `169563cf4f0d36e7be8ad6600c941e0139126cf7`；head `3bddb5517084d59efceb50da2544dd9fd6279d26`；合并前main `ad68168a3f397ce42cb13415204f23b1962024dd`；merge `84c07af2aa8cdb74e23dbdb3b3d63faa52fcae0d`；分支receipt `b9ddc551db914a43b10172ddd5780205`、最终报告 `artifacts/harness/20261020T234754Z-53285edb/report.json`及checkpoint `checkpoints/20261020T235107Z-p01-outline-oracles-done-6fcef9e3` | 16项独立契约测试；12版本/11可见/3样本，固定许可/摘要，关系、精确L2/BM25/图与训练组/成员真值，int8/NULL/版本/重复/缺模态负例。root独立复核，无阻断；不证明实际模型或产品质量 |

<!-- PR15 原始策略/历史事实补充；当前事实以本页最新集成记录为准。 -->
P05 probe初稿004561f2经ROOT与架构师167176 SOURCE审查：真实query身份不一致、启动前归属证据/unknown清理、T0内部截止需修，尚未新构建/性能运行。p00有限修并加4个launcher负例；256MiB/32MiB只是ROOT事前试验profile，原8192/两Parquet/32批/三列1000/5cold+warm和10s/RSS512MiB不变。该16:34快照保留；B2后续实测见下节，P05后续环境/规模STOP另记，不能将旧SOURCE状态当当前结果。

C架构只读复核7a2c1a53列出真实供应方缺口：PG受控父期限/取消与未知bind未获pin时按原request精确cleanup。查无query不能宣称终局；若阻止未来迟到重建须独立持久合同/配额/迁移，现未实现。全历史功能首次率未知；unit、3组件命令、证据工程分别记0/1、3/3、0/1，不把它们混为新用户功能率。下一正式用户结果仍是主线S-SCAN再I1，当前尚未交付。

## B2 FIRST79 与真实三CLI（17:00 UTC 后同步）

源33 `a509e6e28aaa75609651d9fea88f36f5bc7c7413ea0dfef97fca6de832d7d23a`：79/79（原65+新14）内部1.150s/外1.400s；功能原10+located4、性能原8+located4、故障原26+2=28，各首次命令rc0。报告依次`617d583f`/`6f77b405`/`f0799724`，外24.242/17.182/5.993s。实际fixed VersionId与direct SDK/镜像摘要相符；full11和双源130的64/64/2、重放定位、联合A+P输出和失败父账均由本次真实driver检查，未用B1报告顶替。

安全索引`26cb034c`实际532份/14,122,054B，其中65个故障.bin由objects.json精确SHA/size/ref许可，497份driver声明原件逐核；privateLab未纳入，也未重扫旧450或LLVM。运行前后33源/receipt/index不变，Docker三类与基线一致、自有PID/PGID退出，释放`cb0b8b4e`。SOURCE非作者审核`dc5e657f`/`316b8dc9`已通过；本次p01独立实物复核`6f5b29dc`通过（532/65bin/14Parquet/52原A+24located/864对位行逐核），strict/full/提交、P06构建消费、PG/Rust/正式入口与I1尚未完成。旧B1 oracle和工程索引FAIL保持其原始结果。

P05纯launcher四项单元在独立命令首次通过（0.050s/0.149s），不是native样本。旧精确镜像`debb142e`缺失的只读预检失败`ffae4667`保留，tests/mutation均未启动；后续不同实际镜像`c9494374`另获Linux aarch64、rustc/Cargo1.90、rustfmt1.8版本证据`4535a1eb`，不沿用旧55结果作为新镜像证明。单次fmt实际成功但example展开为648行，`59f4d339`记录STOP、build/probe未启动，资源释放`84287414`。机械split source35经ROOT逆合并逐字复核后完成两文件fmt，main583/helper78；后续首次构建及真实组件结果见下节，不放大预算或缩减原样本。

## 17:13 UTC P05真实Arrow/DF组件与当前等待

P05 source35 `4ec8eb51`：机械拆分经ROOT逆合并全文复核`e2e395c3`，两文件fmt后main583/helper78无额外变化；新环境首次offline example build13.892s与driver22.801s均成功，资源释放`54381502`。报告`67ee19bf`实际7个Linux进程/12请求，独立PyArrow真值核全main10+mirror1、8192行/两4096文件/32完整批/三列全排序LIMIT1000；5fresh进程各cold+warm共10性能样本。no-LIMIT同8192在32calls/strict-decodes/materializations后准确resource_limit，未降低输入换结果。

这认证cooperative SealedFixture与真实Arrow/DataFusion组件；provider对象IO为0与宿主Parquet/ledger/输出真实IO分域，不能包装真实P03/P04/PG调用。最大性能样本本体total wall1.661404s、含completion tail为1.662153709s，进程VmHWM56,528,896B；actual Arrow/DF pool peak仍未知，非native内存/取消硬隔离。256MiB/32MiB事前trial、原Arrow64/DF32/结果2MiB/1000行、10s/RSS512MiB均未改；OS缓存未控。p01非作者实物复核`c3dc2e9d`通过（245份/27,964,031B当前安全原件、12全ledger与10×1000结果/lineage逐值核），generic Source/PG/bridge、native硬界、full fault、strict/registered模块出口和I1五项missing保留，完整模块/系统/主线用户链不升级。

ROOT实际fetch时刻17:07:44.138186 UTC，17:07:52读main仍`1e4f6a6`且rootmain干净；本页不把PR分支绿当主线。P02从12:55:43 task-finish至本17:13快照约257.436分钟未main集成，历史108/149/218分钟观测按原UTC保留；其中包括真实消费者接口等待，不全部归因CI。当前无native/service/perf资源窗口在用，B2/P05均在稳定点停止写入，下一C/D由ROOT排供应方与消费者。

## 2026-10-22 本地继续与C1/D1交权（以下保留逐次历史，最新状态见末段）

用户明确答复“暂时继续本地和任务分支，保留远端CI阻塞”。不再等待账户处理才开发，不更改付款/远端设置、CI结果或合入条件。23:52:46 UTC实际fetch main仍`1e4f6a6`；PR15已正常推至`d48a645`，17:19:09 UTC最新API观测的PR/push run `39642553286`/`39642540142`四个quality作业仍0步骤计费失败。这是保留的远端观测，不声称本轮又查CI或远端已恢复。

C1从已验目录`86fcaf0`启动独立follow-up receipt `a4ddd8fa`，p00唯一writer；方案`6fe1d5a7`经p01独审`f08ffa52`通过后，三leaf文档先行再实现。私有父control、真实PG计量与found原request清理不改变A/schema；absence保持cleanup_unconfirmed且不允许自动rebind，持久关闭另列C2。该派发时运行结果待验；后续结果见下文，不能借原目录六轮绿替代C1。

D1方案`e53136f7`/清单`5e71a49b`经ROOT和p01有限增审`971988cc`通过；plan_audit接P05唯一writer，原task`bc81c2ae`/base`1e4f6a6`、原35源`4ec8eb51`及mode已保留，三leaf先行记录`5963d865`后才实现。每页一次strict、Contract+lease驻留，首次decode前锁定字节上界预约；unknown费用及未close credit在Owner中持续可对账，不因局部drop退款。原55/8192/32/sealed性能负载保留；该派发时新候选尚未运行，后续有限结果见下文，真实P04配对仍未认证。

共享实际运行窗预排C1真实PG→D1 Cargo/Arrow/DF，release直接交权；两作者自主局部验证，独审可重叠冻结组件运行。下一真实消费者仍需Source受控PG authority和ROOT D2 bridge原T0/失败尾账/背压/进程wait-reap。此处只改变排程/状态，不改变strict100%、原排除、预算、源码范围或完整receipt义务；尚无新S-SCAN/I1/main结果。

C1最新稳定点：source13 `98b7032d`/delta`f97f36de`，原18保护文件及旧三mode body不变。39纯测通过前的新增13首轮7error保留；39属于Mock/SQLite，未保存完整13源pre-run清单，不把它当严格覆盖或完整源码绑定证明。实际PG每轮source-before/after匹配，control外5.327315s、功能2.047123s、性能30.262958s、故障8.145848s均rc0；最后00:14:46 UTC source13冻结/4自有PID退出/容器空，无HOLD，索引`7ca85c56`。新control为42case（含32父请求），bind+reauth最大25.704ms/1000ms，cleanup最大11.456ms/5000ms。

p01有限实物独审`c8f3c52a`核新control100原件、36条规范query与224121目录字节，未重扫旧4515容量raw。blackhole100.262ms、pausedSQL100.228ms、锁deadline95.554ms、锁cancel26.722ms为客户端调用/FD关闭观测；paused整个故障夹具含unpause约178.019ms，分开记录。远端PG backend停止/PG cancel确认、完整server成本及PG原生内存仍missing；不将此认证升级为真实PG→P03/P04配对、strict/full或I1。C3只读方案正在补原T0、显式网络authority与逐页更小期限，以及精确源码组合闭包。

D1已接共享窗口；首次完整query lib73项中72通过、1失败，原55全通过，实际外16.8525s。新增8192/32受控frame用例在provider费用结算触resource_limit，原日志及冻结源码保留，后续sealed probe尚未执行；作者仅定位收费模型，不抬预算或把失败改绿。这是首轮失败，不纳入新组件通过数。

D1后续有限修复保留首次FAIL：32批调用不等于32 GET，原超8请求用例保留为负例，另用明确无对象I/O的内存byte-provider完整消费8192/32后执行真Arrow/DF。ROOT源码独审另闭合跨页logical_id_asc与close失败尾耗时两项；最终源40 `564efef7`/ROOT审`6f8c01d4`，原55不变、完整76/76通过，外16.102537s。原sealed probe首轮rc0/21.849967s、5进程10性能样本；实物独审`1d333d65`已有限通过。该sealed性能只作共享执行回归，新port独立性能/P04/PG/IPC/native硬界及strict/full仍missing。

C3本地候选已按独审`0a328cf5`建立新树`/Users/chad/dev/guradb-c3-controlled-read`、branch`codex/c3-controlled-read-pair`、task`a8bd6e4158e448298bf3016dead9b43e`，原base`86fcaf0`，正常merge --no-commit精确`b3dd39f`；六共享冲突已保全stage1/2/3，P00唯一writer合成。以最新C1完整13 `c2f3bdc0`及B2非共享26逐SHA恢复，八个共享文件保留两边命令/预算，恢复会话已派独立审查；两旧脏树与receipt不动。这是已标识SOURCE快照集成例外，不是依赖commit、pair或main通过；正常门禁、hook/post及依赖合入后精确HEAD复验不免除。

首次启动的代码绑定报告、复核和checkpoint在`delivery-progress`任务receipt归档；当前进度更新由`w0-status-local-simulation`独立receipt记录，门禁和最终提交证据待完成。本文件中的实施中状态不能当作任何门槛通过证据。


P02固定目录首片：task `08a01f79d8a347b0b429e072167318c3`，分支 `codex/p02-fixed-catalog`，worktree `/Users/chad/dev/guradb-p02-fixed-catalog`，原始base `4d6baca888421d90f146679ef71b0e555fe60881`，checkpoint `checkpoints/20261021T015356Z-before-p02-fixed-catalog-eee85479`。root为当前唯一作者，p00曾在明确交权期间完成facade/admin/mutation/binding/单测/driver后已正式停写交回；root补COMMIT中断、真实暂停commit与负例，并串行接用户导航/共享harness。局部证据与原始范围见[变更计划](../design/fixed-catalog-change-plan.md)，保护authority仍是显式可信fixture，真实PG/对象/源/I1不得由单元结果推定。

PR#9精确主线报告为 `artifacts/harness/20261021T013721Z-42424eaa/report.json`，SHA `1ac66d36a01bb586e309d38ae31d5718e164cc5d863f1a6e7d8553213b4a0225`，checkpoint `checkpoints/20261021T015015Z-p00-cf1a-main-verified-5ce1adab`；PR CI run39525801267和精确主线push run39528308712的Python3.11/3.14均success。上文P00早期Clippy失败是保留的历史现场，不是当前阻塞；该失败报告没有被拼接成修后通过证据。仅离线合同首片闭合，B/C及整体计划仍未完成。

P02恢复承接：新 `/Users/chad/dev/guradb-p02-fixed-catalog-recovered`、branch `codex/p02-fixed-catalog-recovery`、task `5d1ffe780f3b4001a706a0d96a925a77` clean原4d先启动再FF17d，原base保留；root合成6共享、900watchdog、PG3driver对应275分钟工程job及hosted负例当前change适配。原08a/dirty/raw与首次重启FAIL保留；旧c480观测场景通过不补齐FC10其它quota或新fullcheck。细节见本片变更计划，后续新增源/索引/PG真实配对及I1仍待验收。

P02恢复树新增五项行容量的直接补证已完成：64grant、256identity、128target、1024query和16dataset，并保留原512operation及8MiB字节负载，原120秒上限不变。performance报告c49472bc用时31.526968秒、独立combined审查03b40a46逐核4516原件/4509正文；两历史grant仅重建，不计作历史raw。当前结果属于运行前2432清单，随后仅结果/导航文字更新，新完整checkout门禁仍pending。旧595551失败、旧c480局部结果及旧08a abandoned现场保留；实际命令、路径和未覆盖项见[目录变更计划](../design/fixed-catalog-change-plan.md#恢复树-fc10-七容量的实际结果与独立复核)。

P02已从原4d在全新/Users/chad/dev/guradb-p02-fixed-catalog-main1（codex/p02-fixed-catalog-main1/taskb826fc2af8cf4ebcbf2142ec6b6913f8）先clean task-start再cleanFF已闭合1e4，34源码/模式等09856备份；root逐实物复核receipt/5上游/empty index后只补内部状态。旧5d1/08a与raw留原位；新checkout正常hook/完整原base freshpost、PR/main仍pending，不将2432七容量组件当新整项通过。
P03原始范围恢复：旧dirty树与task653a及全部局部raw保留；新 `/Users/chad/dev/guradb-p03-fixed-objects-recovered`、branch `codex/p03-fixed-objects-recovery`、task `aa7ad841fd3a456ea99eb2e1ddcfd8ca` 在clean原4d先启动，再FF合入PR10的17d。19独占源码逐字转移，root串行合成6共享域，保留900秒coverage工程watchdog。增加3条driver后普通CI按实际ready命令重算为275分钟，并明确排除Lab两份私有测试配置；各产品/组件预算、原负例及覆盖豁免不变。恢复当时，完整原4d范围的新checkout验收与实际上传边界均待运行；现本地INITIAL见下，实际上传边界仍待验证。旧26/230/3804与三driver结果不能代替新fullcheck。恢复当时PR10双版本PR CI已成功、精确main验证仍进行中；现root已核验merge17d的main报告044402-982e5f80（SHA6d0e4932cf0c34fc263caf526ad00c013ad640ca4ae28adccaeea3d91ffe45ec）、checkpoint044927-pr10-main-verified-935740fd及PR39544118302/main push39545360623两Python版本均SUCCESS，已闭合。P03首次新INITIAL原472440范围运行9suites/33paths，报告b76b292d保留FAIL：八suite分别通过，仅既有hosted-limit负例的change250夹具前提未适配新272最低预算而失败。按先行计划仅修该夹具并冻结28文件后重新执行完整INITIAL；首FAIL原样保留，不拼其它局部结果为通过。

本轮新28文件manifest64f1cd3a在独占窗口先跑完整CIworkflow模块5tests，再以matching新venv运行原4d完整INITIAL九套件/33paths/26命令，全PASS；报告 `artifacts/harness/20261021T053114Z-e7619721/report.json` SHA `0e4364576a90dc69331eca368367e25f42eed3590d3ba251572338c5f28f965b`、checkout `e8798305c8b4fd87d31296e8c42fe3b94386c1432c3ae2ec52a4e3c04af59998`。Python232项/3804行零排除、Rust3323/3323和原21行豁免、9phase起止与3真实driver均重测。root匹配解释器validate_report、完整argv/log/hash/输入身份及28scope累计计量和期限/关闭记录已独立核验，review8ccce124；新790 profiles在任何后续cargo前保全，旧首FAIL/793profiles保留。本轮随后只更新结果文档和导航，新的docSHA仍需最终commit精确原范围postcheck。正常hook/commit/task-finish/公开raw归档、当前PR双Python CI/实际上传ZIP私有配置排除、merge后精确main本地及双CI仍待完成；PG/P04/I1、真实云、多机与完整产品门禁仍missing。

P03当前source-only接续树为/Users/chad/dev/guradb-p03-fixed-objects-main1（codex/p03-fixed-objects-main1/task55eb29fb62c645c48dc205760a089a2c），clean原4d先receipt再cleanFF1e4，完整28源码/模式等7ba8备份、5上游P05文件未变，root已复核；仅内部状态文字更新。旧aa7现场/receipt仍待确认全部承接后abandon，保留首次FAIL及原9suite INITIAL。新checkout正常hook/原base提交后检查、PR/ZIP排除认证及I1仍pending；PR11精确main本地已过，双mainCI尚运行，禁止下一PR提前合入。

<!-- PR15 原始策略/历史事实补充；当前事实以本页最新集成记录为准。 -->
恢复核对：main干净且仍`1e4f6a6`；策略receipt`4f36dc71`与C3 receipt`a8bd6e41`保持active。旧agent已停止，新会话只读核对现物后接续；C3候选67路径/共享8文件仍待新独审，冲突index与旧stage原件保留。D1独审`1d333d65`绑定源40及释放`5281f76c`，有限确认76 lib和原sealed回归；新port性能、真实PG/P04/IPC、完整模块/系统仍未通过。D2仅接口方案，未开始真实bridge实现。

## 2026-10-24 有限集成口径

本页旧 ROOT/PM 角色与等待状态保留为历史。当前独立 PM 会话通过 GitHub Issue19 负责优先级、依赖、阻塞升级与交付跟踪；ROOT 负责实施、验证及有限整合。用户本轮豁免远端 CI 容量/账户阻碍，不代表 CI 已通过；本地完整命令、原预算、strict、负例和发布 missing 义务保留。当前仅整合已有有效交付，不恢复无限新增开发。
