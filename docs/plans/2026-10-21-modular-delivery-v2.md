# 实施策略 v2：模块交付与连续配对

2026-10-21。执行决定见 [ADR0022](../decisions/0022-module-delivery-and-validation-levels.md)。本页替代旧并行计划中的任务粒度、排程与日常门禁安排；P00–P20、I1–I3、G1–G5 的产品验收义务保留。需求以[功能矩阵](../product/requirements-v2.md)为准，模块职责与运行时权威以[模块交付合同](../design/module-delivery-contracts.md)为准。

## 当前交付目标

先使用户在主线重复得到：登记已保护固定输入 → 真实 PG 绑定 → 固定对象与 Parquet → Rust 过滤/排序/投影 → HTTP 与 PG 返回相同 ID/version。扫描链先形成可运行小片，再接 BM25/精确向量完成 I1；随后图文实际取字节与更新完成 I2，实际训练框架消费完成 I3。每个系统检查点保存教程、独立真值、负例、精确 main commit 与复现命令。

工作单位改为“需求 ID + 可消费接口 + 可验证出口”，不等待整个 P 包完成。边界经架构与消费者必要复核即实现；模块稳定即约真实配对，配对中发现的接口问题回到唯一 owner 修订。完整合同、模拟互通、模块实测、真实配对和用户系统结果分别记账。

## 四个槽位与交接前职责

| 交接前槽位 / 具名负责人 | 旧会话任务及唯一文件域 | 下一职责 / 独立审查 |
| --- | --- | --- |
| ROOT：项目经理、集成与文档 | `codex/strategy-v2` 已结项至 `d48a645`、[PR15](https://github.com/yizhouxw/guradb/pull/15)；本轮 task `4f36dc7140274d578ba88507369aa483` 从 `d48a645` 续记四份事实文档，ROOT独占写入 | 优先级/共享文件/资源/阻塞与组合根；四槽位最多两项行为实现，独审与作者分开 |
| p01_oracles：产品经理、测试 | 42条需求与独立真值；C1方案及D1单次strict/父预约增审已通过，当前保留独审槽接冻结SOURCE | 审C1/D1边界、真实性能/恢复与随后真实配对；自身oracle由ROOT或非作者审 |
| plan_audit：架构师、模块开发 | P03/P04源码与已验B2冻结；已临时接P05 query D1唯一DRI/写权，原task `bc81c2ae8eb94fb99a646c061a61c35c`、base `1e4f6a6`不变，原35逐字节/mode保留 | 实现私有真实Source消费者；其实现由p01/ROOT审。不得同时修改storage/connectors行为；D1稳定后再显式交权 |
| p00_cf1a：模块开发、工程工具 | catalog C1唯一DRI/写权；`codex/p02-fixed-catalog-main1` 新task `a4ddd8fafdf04304a24bd4f474831ca5` 从已验 `86fcaf0` 续做父期限/取消与原request清理 | 新control及原三模式已实测，p01完成客户端控制有限独审；窗口00:14:46 UTC已交D1。当前只读准备C3真实读取接口，不并开第三项实现 |

同时最多两项行为实现，保留审查能力；角色数不等于并发数。普通无污染单元、源码审查和隔离功能夹具可并行；性能测量独占同一物理资源，coverage 互斥其 target/profile，迁移/组合根有唯一窗口。端口、网络、对象前缀和数据目录必须各自隔离，不把所有测试长期串成整库窗口。

旧会话上表中的具名agent已全部停止，保留其历史DRI及文件归属供追溯；恢复时不继续旧agent。当前ROOT独占四事实文档，新的`c3_review`仅独审C3候选，`d2_plan`仅调查D2接口，`facts_review`独审本轮文字；三者均显式medium、无行为源码写权。C3实现由ROOT在共享审通过后另行交权。

## 当前本地派发与集成窗口（2026-10-22）

用户明确选择继续本地及任务分支，保留GitHub账户计费/CI阻塞；不豁免双版本PR检查，不合入main。最新fetch为2026-10-21 23:52:46 UTC，origin/main仍`1e4f6a6`。本轮两个小片如下：C1客户端控制组件已独审通过，D1修复后76项lib与原sealed回归已通过、实物独审`1d333d65`已有限通过；完整模块与系统仍未通过：

| 小片 / 唯一实现DRI | 已复核边界与本轮出口 | 下一验收 / 消费者 |
| --- | --- | --- |
| C1 / p00_cf1a | 私有父control从bind前起算；原request一次bind、真实PG invoice、found精确lease清理；A/schema不变。absence保持cleanup_unconfirmed、不自动rebind，durable闭合另列C2 | 32个1000ms父请求及边界实测已获有限独审c8f3c52a；客户端返回/FD关闭通过，远端PG停止确认、完整server成本/原生内存未证；下一C3真PG→P03/P04配对 |
| D1 / plan_audit（临时query DRI） | 同一Rust Compiler/Arrow/DF；单次strict解码Contract+父lease驻留，前置按锁定纯字节模型预约，unknown费用/close credit留Owner至可信ack。原55及sealed8192/32负载不变 | 受控byte-provider模块fixture+真Arrow/DF；不是P04 pair。随后ROOT装配D2真实P04桥，补原T0/父账、失败尾账和kill/wait/reap |

作者可自主完成范围内普通单元、格式/600行与只读环境预检；SOURCE冻结后独审可与实际组件测试重叠。真实性能/Cargo共享窗由C1先用，明确释放后D1直接接权；HOLD未清不交窗。首次FAIL保留并定位，有新修改/风险才重跑相关测试。原strict100%、21有限排除、旧receipt全范围和最终M/P/S/R义务不变。

## 首批任务与集成检查点

| ID / 出口 | 唯一负责人；验收与依赖 | 下一消费者 / 阻塞解除动作 |
| --- | --- | --- |
| V2-GATES | p00；`82b2bfe` 工具分支正常 hook/原 base post 各 5/5，非作者独审完成，PR16 待 CI/main | 初始只映射 Rust query/storage 与 legacy-M0；无映射扩大范围。代表性 strict 曾实测 710/711 而失败，不能标模块通过 |
| V2-PRODUCT | ROOT；42 条需求、唯一 owner、预算/错误与版本研究已交 PR15，非作者产品/架构审查及两轮文档检查完成 | 每个开发 DRI；未冻参数/预算的具体需求先交冻结小片，其他已闭合小片继续 |
| M-CATALOG | ROOT 闭合已验 P02 分支：`86fcaf0`，真实 PG 六轮证据已独审、task-finish/正常推送已完成；[PR14](https://github.com/yizhouxw/guradb/pull/14)已创建，双 CI/main 待闭合 | PG 父期限与对象授权配对；连接器 HTTP429仍保留；ROOT已用现有认证的标准API解除PR创建阻塞，继续跟踪CI，不阻止本地模块 |
| M-STORAGE | plan_audit；原诊断 FAIL 保留。新 source44 `2d1dfa7d` 已通过 60 项单元及原只读功能12/性能4/故障12，ROOT与p01独立核原件；原 4d receipt 的 strict/full/提交仍待完成 | 已解除 P04 配对等待；全部合法 special key 固定 GET、0IO dot 拒绝、预算/费用均保留；SDK 写入诊断仍不改 8 为 7、不标绿 |
| M-QUERY | plan_audit当前接D1；p00历史Describe 补测 `ad5c9fe` 的正常 hook/clean post 均 9 suite/11 命令、完整12生产源 strict 与原三个 M0 已验，task7c822 已结项。P05 新 source31 `c32f44b6` 首次完整 lib 55/55，经 p01 非作者实物复核 | P05新sealed Arrow/DF组件性能已首次实测、非作者实物审c3dc2e9d通过；strict/full fault及真实Source消费者仍缺；保留全11成员/8192原负载，不以旧M0证据代验新M1 |
| P-OBJECT-SOURCE | plan_audit 实现、p01与ROOT独审：新 source28 `51601127` 的 44单元、原6功能/4性能/23故障实际通过，真实 P03→P04 单 SourceVersion 读取；资源已释放 | A 本地配对稳定点；不是完整多来源 B、整项 strict、PG/Rust、主线或 I1。下一消费者先实现完整两来源及 located 出口 |
| P-CONTROL-READ | ROOT 装配、catalog/storage owner 修各自实现：真实 PG 绑定/reauth→对象，同父 deadline/cancel/ledger | Source/Rust；真实暂停 PG、对象故障与撤权；同步 trait 或内存 callback 不能充当网络期限认证 |
| P-SOURCE-QUERY | ROOT 组合、两端 owner 实现：有界私有 bridge，Python 真源→Rust 唯一 SQL/Arrow/DF，完整两来源 11 成员/稳定 ID | 正式 HTTP/PG；限定 IPC/错误费用/取消与 reap 证明先复核，不另建 Python SQL 引擎 |
| S-SCAN / I1 | ROOT 批次集成，p01 独立用户旅程：先 PG→S3→Parquet→Rust 扫描端到端，再接 P06 候选/回表/正式入口完成原 I1 | I2→I3；扫描成功单列，不把它改称完整 I1 |
| R-PG-PHYSICAL | p01 研究/原型，connectors DRI 接后续实现；[独立物理路径需求](../research/2026-10-21-pg-physical-ingest.md) | 目标版本/扩展/API/一致性/恢复规格；不阻塞对象湖 I1，也不拿 wire/COPY 成功替代物理导入 |

稳定点在下一调度轮、目标 30 分钟内指定 reviewer 和消费者；真实配对在下一可用资源窗口、目标 2 小时内启动。超时记录 `blocked_since/owner/reason/next_action`，超过一个工作日必须拆片或明确重排。这些是调度目标，不是数据库 SLO。ROOT 每轮主动处理等待，不让已稳定模块因未完成的大包长期空置。

首轮实物接口核查后，将上述配对拆为以下可交接小片。p01 负责独立真值与验收；每行只有一个主实现 DRI，供应方接口仍由原模块 owner 修改，ROOT 不在组合根另写模块语义。

| 小片 / DRI | 固定输入 → 验收出口 | 开工依赖与已查明缺口 |
| --- | --- | --- |
| A / plan_audit | P03 真固定 metadata/Parquet → P04 单 source 真 ReadBatch；逐 cell/ID/version/费用及坏 footer/撤权/取消 | P03 读取稳定即可启动；构造接口现可相接，不等 PG/Rust/index；通过只记单 source pair |
| B / plan_audit | 同一完整 revision 的 main10+mirror1 → 全 11 成员与显式 located 描述符、同父账 | A；B1两来源和B2 located首次真实组件已通过，B2独立实物复核6f5b29dc通过。不得拆子 view、猜 ordinal 或省 mirror；保留 1000 行/4 文件/16 rowgroup cap |
| C / ROOT | P02 真 PG bind/reauthorize/release → B 原期限/取消/授权与精确 lease 清理 | catalog owner 先交受控调用接口，storage/source owner 交父控制接入口；现网络 reauthorize 不能直接塞入仅认证内存 callback，真实 PG 暂停/撤权须验 |
| D / ROOT | B 全 11 批流+C 父控制 → P05 唯一 Rust Compiler/Arrow/DF 值、身份血缘和真实账 | P05 R2 稳定后 query owner 先交真实 provider 消费者，ROOT 再写有界私有 bridge；现 `execute_fixture(SealedFixture)` 的 0 对象 I/O 账不能包装真源冒充配对；IPC 取消/回收/错尾输入须验 |
| E / p00 | B located+批流 → 真 BM25/exact 产物；P03 读产物→候选；D 真回表 | B+C；现索引 manifest 仍单 source_version_id，独立 ExecutionScope 仅预计一次/size，须显式迁移并接真实跨 attempt 父账。构建可先于 D，回表完成须 D；保留 100 行/单 shard/1MiB |
| F / ROOT | 可信 principal+view+SQL/typed params → 同一 D/E facade 的正式 HTTP/PG | C+D；P08 只有设计，需真正实现入口、bind 一次/portal 固定、完整 fingerprint、失败账和精确 pin 清理。先正式 scan 检查点，再接 E 完成原 I1 |

顺序为 P03 M→A→B，P05 R2 可与 A 独立；C 供应方接口可先准备，真实 PG→读取需稳定 A/B；D 需 B+C+P05，E 构建/产物读可在 B/C 后、候选回表需 D，F 先接 D。完整 11 成员在既有 cap 内，但不推出 8192/10k 整链支持；P05 原 8192/32 batch 验收另保留。子期限取父更小者，不能将 P04 页/查询、P06 build/query 和宿主预算相加或重开 TTL。各 M/P/S 结果分别记录，A 通过不省 B–F。

本轮已实际启动 A：从 P03 只读组件 ROOT 确认稳定点 14:57:38 到 P04 首个真实功能命令 15:18:34 约 20.9 分钟，15:20 已清理并释放。该记录只计算这次局部交接等待，不把两端历史模块各绿当配对，也不把 A 内单 SourceVersion 的11行当 B 的 main10+mirror1 两来源。B1已接通真实main10+mirror1与双源130；B2 located首次79及三CLI已通过并释放，当前已独立实物通过并保持冻结，P05 probe已首次实测已获非作者实物审c3dc2e9d通过，随后排真实C/D。

## 四层验证和 CI

| 层 | 触发与范围 | 完成含义 |
| --- | --- | --- |
| module | 普通模块变更；该 owner 全部适用生产源码、语言检查、功能/负例/故障/真实性能及自身真实 PG/S3/Arrow 等依赖 | 跨模块依赖可用固定版本契约/fixture；完整模块适用行严格 100%，不缩成 changed lines；不能宣称配对或系统通过 |
| pair | 两端真实实现消费固定接口，模块稳定点或接口变化 | 核同 view/ID/version、错误/权限/取消/剩余费用及恢复；第三方未参与模块可固定替身 |
| system | 稳定小片组成集成批次、公共入口/全局风险及 main 候选 | 当前支持旅程、受影响配对及 legacy 回归；在集成窗口运行，按整个批次基点验收 |
| release | 声明部署的发布候选 | 完整 performance/stability/soak、安全、安装、升级与联合恢复；planned/missing 继续阻断 |

机器实现由 `gates-v2` 任务提供 `--level auto/module/pair/system/release`、明确 module/pair registry 和 v2 证据绑定；**此策略页本身不证明代码已生效**。pre-commit/PR 自动选实际范围；main/system 与手工 release 分开。未知 owner、未认证映射、公共合同或无法证明影响范围的变更扩大检查；显式要求过窄范围要拒绝。报告和 receipt 固定 level、模块、源闭包、命令/预算、profile 摘要与原始任务基点，模块报告不能冒充 system/release。

15:17 UTC 在各最新 head 核对：PR14/15/16/17 的 8 个两版本 Actions 作业均因账户付款/支出额度未启动，执行步骤为 0。没有 CI 通过证据；ROOT 已请求用户处理账户，保持合入条件，继续本地模块/配对。15:18 fetch 的 main 仍为 `1e4f6a6`；工具在 PR16 分支已实现和验证，主线尚未生效。合入按依赖排 PR15/16、PR17（依赖16），P02与后续读取切片按各自原始范围集成；不跳过远端和合并后系统验证。

工程工具变更运行完整 harness 自测、选择器差异、真实 CLI/报告伪造负例及代表性模块路径；不凭空把所有工具源码加入生产覆盖分母。已有生产严格覆盖、原始性能负载/时限、Rust 有限排除和发布义务保持。门禁调整须非作者审查并给 before/after 实际选择与运行耗时；缺失映射公开列出，不把“有 registry”当已优化所有模块。

第一批保持 main 候选 system 验证，ROOT 将稳定小片聚成集成批次，减少候选次数。未经正式证据复用协议，不跨 commit 拼接旧绿色报告或 profile；先通过范围缩小、明确资源归属和锁定依赖缓存减少重复。任何复用优化都必须验证完整输入闭包、选择器/预算版本及来源，明确引用旧执行，不能伪造 fresh。

## 用结果与阻塞校准速度

每个需求分别记录 M/P/S/R 状态与精确证据；未运行记 pending，已失败保留失败及原因。报告至少给：已验功能点、真实用户链路、关键路径剩余项、阻塞 owner/起点/解除条件、等待集成分钟、验证命令耗时及首次通过率。

首次通过率 = 首次完整计划执行即通过的功能点数 / 已有首次完整执行的功能点数；环境预检、实现、oracle、门禁与证据失败分别分类，未执行不计分母。不使用最终绿次数作分子；逐重试成本保留。Rust 行为、公共合同、测试、工具分别统计变更，不把合同/工具行数算用户功能。

工程优化排独立任务：实际镜像/平台探测与共享夹具、锁缓存/普通编译复用、模块覆盖分母与串行 profile、防重复质量运行、一次清单安全归档、恢复按故障范围处理。SOURCE 交接只核本次源/契约/必要证据，不反复扫描所有历史 profile。进度以[实施事实账本](2026-10-21-delivery-progress.md)为准，不按包数或代码量虚报完成比例。

作者在最终SOURCE冻结前完成目标文件fmt、600行检查和只读镜像身份预检；普通无污染unit/format在既有明确授权内自主执行，不逐次等待PM。PM协调共享native性能、迁移和coverage资源窗口。源码或环境变化只增审必要delta；精确镜像缺失必须停报，不能静默换镜像或跳过原负载/strict。此次648行晚发现和旧镜像缺失分别保留为规模/环境工程成本，将检查前移，不把“先SOURCE再等formatter”固定成新等待流程。

## 16:34 UTC 可执行检查点

| 当前出口 | 已验事实 / 下一动作与唯一负责人 |
| --- | --- |
| B1 真实双源批流 | source30 `0de215b4` 的65单元、10功能/8性能/26故障通过，独审e8a78f02；main10+mirror1与双源130全局64/64/2共用父账。只认证本地组件与真实P03配对，不是strict/full/main/I1。 |
| B2 located / plan_audit | 沿已审联合输出合同实施SOURCE；A+P≤原768KiB、有限32轮长度固定点、最终hash/定位/费用方程与fresh授权后一次交付。拒绝整页超限，不缩旧页/猜ordinal/偷读_state。 |
| M1 probe / p00 | SOURCE33独审需修query身份、启动前durable归属/精确owner/unknown HOLD/主错误保留及T0单调下界；加4个launcher负例，原55与8192/32批/三列1000/5cold+warm不变。256MiB/32MiB是事前冻结试验预算，非实测生产默认。 |
| C / ROOT装配、原模块owner供应 | bind前T0/取消/page较小期限尚未传PG。按完整原request与principal清理已持久query是有限候选；absent不能终局，阻迟到重建须独立持久closed-request配额/版本/迁移合同。PG等待/缓冲不计0，当前仅设计。 |
| CI / ROOT | `23a2e37`去重工程片已正常hook/post5/5并独审；PR auto/main system/manual/schedule/release保留。15:54仅观测该head的PR run，两个作业0步骤计费失败；16:10:57 fetch主线仍1e4。账户阻断不阻止上述两个本地切片。 |

首轮新增unit时钟oracle失败与后轮外层证据索引失败分别记账；所有实际组件已过，59个原故障.bin按objects.json补索引而未重跑。原window FAIL和系统default bridge ID变化均保留，独立确认自有资源退出；不把补证当作重写绿色。原模块严格100%、完整任务与系统/发布义务保持。

## B2 首次真实 located 检查点（2026-10-21 17:00 UTC 后事实同步）

B2 source33 `a509e6e2` 保持原task4696/base17d、P03七生产源与普通A路径：FIRST79单元通过（内1.150s/外1.400s）；原CLI首次功能`10+located4`、性能`8+located4`、故障`26+located2=28`均通过，分别24.242/17.182/5.993s。原10/8/26与全部输入/cap未替换；全11与双源130定位由独立PyArrow回表，同一父账联合封套A+P≤768KiB。原件532份/14.122MB含65个objects.json逐件绑定的故障.bin；源33/receipt/index未变、Docker三类回基线及自有进程退出，release `cb0b8b4e`。p01独立实物复核`6f5b29dc`通过；这不是P06消费、真实PG/Rust/I1、strict/full或主线验收。B1时钟oracle与旧外层证据FAIL原件保留。

P05四项纯launcher单元首次通过（内0.050s/外0.149s），不计native/perf。历史镜像`debb142e`缺失在只读预检即STOP，无质量命令/镜像替换；后续另行认证实际镜像`c9494374`的Linux aarch64、rustc/Cargo1.90与rustfmt1.8，不声称与旧镜像等价。该新环境单次fmt成功后example实际648行，按600行规模纪律STOP，未build/probe；作者按职责拆分source35并完成两文件fmt（583/78行、无额外字节变化），首次构建与真实组件的后续成功结果和仍缺范围见下段。新8192/两文件/32批/三列1000/5cold+warm、固定256MiB/32MiB试验父预算和10s/RSS512MiB均保持。

本页当前事实快照：2026-10-21 17:13:09 UTC。P05 source35 `4ec8eb51` 的首次offline build13.892s/driver22.801s通过，7个Linux进程、12请求、10性能样本，最大perf样本本体total wall1.661404s、含completion tail1.662153709s/VmHWM56,528,896B；full11、8192/两Parquet/32批/三列1000与no-LIMIT完整读取后资源拒绝均实测，释放`54381502`，p01非作者实物审c3dc2e9d通过。只认证cooperative sealed-fixture真实Arrow/DF，不认证generic Source/PG/bridge、native硬界、full fault、strict/full或I1；上述历史镜像缺失与fmt648 STOP不改绿。17:07:44实际fetch仍main1e4，当前资源窗null，P02等待值及原历史UTC见事实账本/JSON。

C1本轮真实PG新增control外5.327s、原功能/性能/故障外2.047/30.263/8.146s全部rc0；独审核新control100原件、42case/32query，不重扫原4515容量raw。D1首次完整lib为73项/72通过/1失败，旧55全过；8192/32新frame用例触费用上限，保留FAIL并定位，不抬预算。两片当前结果与完整模块/真实pair/I1分别记账。

D1最新源40 `564efef7`已获ROOT非作者SOURCE审`6f8c01d4`；全76 lib通过（外16.103s），原sealed回归5进程10性能样本通过（外21.850s）。新port独立性能、真实P04/PG/IPC、严格模块出口仍未认证。C3已建独立本地SOURCE候选`codex/c3-controlled-read-pair`、task`a8bd6e41`，P00唯一writer合成共享冲突后才实现；旧两树不变，新会话独立reviewer审共享8文件及67路径闭包，不把未提交快照称上游已交付commit。

## 2026-10-24 有限集成口径

本页旧 ROOT/PM 角色与等待状态保留为历史。当前独立 PM 会话通过 GitHub Issue19 负责优先级、依赖、阻塞升级与交付跟踪；ROOT 负责实施、验证及有限整合。用户本轮豁免远端 CI 容量/账户阻碍，不代表 CI 已通过；本地完整命令、原预算、strict、负例和发布 missing 义务保留。当前仅整合已有有效交付，不恢复无限新增开发。
