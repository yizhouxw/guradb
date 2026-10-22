# P04 固定源用户场景与验证映射

## B2 located 增量（先行；全部待验证）

| 场景 | 独立断言 |
| --- | --- |
| FS10 同页定位 | full11 main10/mirror1与双源130原64/64/2页；A/P同context、精确batch SHA、ordinal/last、逐ID/version/cells SHA、一一同序；独立PyArrow按实际固定ObjectRef/RG/offset回表全值，不读_state。 |
| FS11 共同计费 | D=本页真实父输出prefix，u=D+len(A)+len(P)，32轮有限fixedpoint/十进制阶跃与最后方程验证；每次父账delta精确等u，不重复扣D，重放定位/记录保持、hash随真实Usage自洽。 |
| FS12 联合拒绝 | 原A可容但A+P超768KiB、预算仅够A、live预约不足、错hash/context/cells/外来或越界locator、非canonical/未知字段均拒绝整页，无半sidecar；不改原页表/预算。 |
| FS13 最后交付 | 完整构造校验/预留后fresh clock/reauth/取消，唯一delivered(L)；晚撤权/到期/取消、第二源坏或缺版本无A/P交付，原prefix/attempt账保留、state poison；非owner并发拒绝不伤owner。 |

保留原65定义与真实10/8/26工作量/期望，只追加独立located单位和真实cold/warm/故障case。历史B1组件证据不是B2验收，外层工程FAIL不改绿；IPC/P06/PG/Rust/I1继续missing。

## B1 双来源增量映射（先行；全部待验证）

- FS01/02/03：两个真实 metadata/Parquet 对应 main10 与 mirror1，显式 SourceVersion/field-ID/身份映射；逐 ID/version/cell 和实际物理位置核独立 PyArrow，保留 r-a1/2 与 r-a1-copy/1、NULL/int8；源声明顺序不能改变完整逻辑集合。
- FS04/06/08：一个固定 binding/scope/账本与全局 ordinal，所有来源联合计 64KiB metadata、4 files/4MiB、16 RG/1000 rows/32 fields/live8MiB 和原页/cohort/父期限；追加双源 cold/warm，实际无重试冷 4 GET/暖 0，全页与重放 0 重绑定/0 漏 mirror，不相加两套独立 Usage。
- FS05/07/09：第二源损坏或缺对象、跨源重复 ID、错 schema/field/identity 策略、交叉/额外对象、联合上限、超过两源、第二源前预算不足及晚撤权/到期/取消均失败且无部分页；保留失败父账与原清理语义。

原 44 unit、6/4/23 场景全部保留；新增 `test_fixed_sources_multisource.py` 与既有三 driver 增量在 SOURCE 独审后另排窗口。前次单源配对绿不补本轮绿；B2 located、P06、PG、M/P、I1 不在本片完成声明内。

FS04/06/08 还须追加真实双源 main65+mirror65 的 130 行冷暖、全局 64/64/2 页、0/1/2 ordinal、last/重放、同父账与逐行 PyArrow locator；旧单源 130 行与新 full11 两源各自保留。32 字段联合定义为 Resource≤32 且Σ完整 source_schema字段≤32，先预检再分配 data/记录工作集。

当前源码定义为原44加新21项 unit；functional10/performance8/fault26 包含全部原6/4/23。新增 full11 与双源130各有 cold/warm，跨源 metadata/数据损坏及重复 ID 为三个新故障；这些定义全部待首次运行，mock 传输负例不认证真实网络或时限。

FS06 首验补充：`492740ca` 的65 unit 实际64pass/1fail，三个CLI未启动；新增测试误将双真实时钟下的合法deadline收紧当作失败。保留该函数内原严格相等断言，改用确定wall/monotonic输入；第二次重放只推进wall1ms，严格核deadline减1ms、started不变、同父账及0新IO。该oracle修订须独审后复验，原44/21定义数量及产品预算不变，Docker bridge变化另行对账。

## 本轮 direct 夹具修订的验证映射（全部待验证）

- FS01/02/03/04：保持原 6 功能样本、固定 VersionId、完整 11 事实、130 行两文件和独立 PyArrow schema/位置真值。只将 SDK setup/upload 改为显式 direct；生产读取仍经真实 P03 FixedObjects 与同一 SourceScope。
- FS08：保持原 4 冷暖样本、请求/字节/内存/1 秒页与 5 秒 cohort/RSS 预算及 OS cache 限制。新版报告单列 SDK direct 与实际镜像/平台/SDK 版本；旧 SDK proxy 前提不能由 reader 的无 ambient proxy 特性推断。
- FS05/06/07/09：保持全部 23 故障 case 与 38 项既有 unit 原义。新增纯 unit 验证 direct 请求、实际安全身份摘录及错误前提拒绝；mock 不认证 SDK、Seaweed 或跨平台行为，不默认启动服务或复制 P03 dot 诊断。
- 真实复验仍使用既有 functional/performance/fault CLI，各新 run-dir 必须绑定当前源码/锁/输入 before/after。缺少 direct、版本或六字段镜像证据须失败；实际 architecture 是观察值，不据此声称另一架构已认证。

本轮 SOURCE 修订尚未运行；下文保留各历史阶段的先行合同和后续实测更新，不能当作本轮通过。

新证书前仍有 Lab 原有 setup 操作；只保证 P04 专有上传在证书之后。SDK client 独立 close 未认证，不将 Lab 服务清理或 source 连接清理扩称为全 SDK 生命周期认证。

全部状态为待实现/未测。先行手册见[固定源](../user/fixed-sources.md)，实现/风险/预算见[计划](fixed-sources-change-plan.md)。

| 场景 | 操作与独立断言 | 计划入口 / 证据状态 |
| --- | --- | --- |
| FS01 固定源 | 相同published binding读取精确metadata/data版本；新发布不换旧query | functional + 独立ObjectRef/完整P01集合；missing |
| FS02 真实schema | 独立footer核全部physical ID/type/nullable和metadata完整schema摘要，重排不猜位置 | unit + 真实Parquet三group；missing |
| FS03 身份与类型 | identity/key_v1/revision_version，int8两极、NULL/空/false，真实逻辑ID/版本全量比较 | independent oracle + functional；missing |
| FS04 分页与物理位置 | 至多64行/768KiB page、终页、同page重放、跨binding拒绝，排序前物理位置逐行保留 | 多文件/多page独立reader；missing |
| FS05 fail closed | unknown/delete/schema evolution/缺对象/坏hash/footer/重复或NULL key/过长key/假版本拒绝 | unit + fault；missing |
| FS06 授权和预算 | 每次输出当前授权；重试/cache/page累计真实I/O；原wall/mono期限不延长 | P03真实计量配对 + cancel/revoked/budget；missing |
| FS07 受限decode | 仅无压缩无字典V1纯Python；native/压缩等拒绝，恶意长度/深度/run先限后分配，原deadline逐步取消 | 机制先行独立review + 真实Parquet/坏页注入；missing |
| FS08 有界成本 | 固定完整输入，cohort5s/page1s/RSS512MiB及原context更小预算；公开冷热与wire/Arrow成本 | performance独占窗口；missing |
| FS09 兼容与恢复 | legacy入口不变、unknown新codec拒绝；失败保留原件/新目录恢复，不回收源/pin | 静态/负例/实际恢复记录；missing |

前置只允许可信本地开发测试身份，锁定依赖和P01固定许可合成数据；无源writer/目录发布/GC权限。empty源、多source、Iceberg、B-L、真实PG/SQL/HTTP及I1不由本表授权，未有实际证据均missing。用户操作预期、支持/拒绝和预先冻结规模/资源见手册；文档可达不证明行为通过。

每项补实际命令、commit/checkout、input/config/锁摘要、报告/raw路径、独立review和未覆盖项后才能标支持。首次失败原样保留，不拼其它suite通过。当前有先行文档、task713da247/checkpoint051951、6个生产候选与20项unit设计；R3源码独审ffbd8cee通过，新增driver候选仍待独审。不存在运行报告。

行为前机制收紧见手册/计划：纯Python窄Parquet、完整schema按ID、source_schema按ID升序、同一P03scope真实累计账与batch delta/活跃memory峰值、768KiB确定性字节缩页。对应FS02/04/05/06/07须有独立writer/reader和真实P03配对；无native能力声明。所有源最大值联合内存不足可在分配前resource_limit，不截断/改schema/偷换负载。当前仅文档候选，须独立准入复核后才实施。

FS01补闭合断言：revision.objects完整集合恰等metadata+files，metadata不得重复/作data、额外对象拒绝，empty仅metadata。FS06补原生scope子类同实例/双锁不嵌套/异thread不混账、首次5s cohort锚不重置及零reserve页活跃memory不丢失；FS04完整envelope<=768KiB而非只算rows。Thrift i64与PLAIN INT64分别按各自线格式，不混用。

FS06/08补真实外层page_elapsed（含终次构造/reauth/清理）、Usage最后观察点及finalization_tail数值；Usage elapsed快照不是完整调用耗时证明。FS05/07补首次scan后最终输出失败必须清reader_state、拒绝续读而父账/P03已收输入不退款。源码R1独审06071321的2项P2按先行合同修订，未运行前全部missing。

FS06补同reader并发所有权负例：T1持有、T2拒绝且不清T1_state，T1恢复正确完成；FS05/06补最终delivered前取消拒绝不增加封套输出，delivered提交后不再策略拒绝。R3修订前先行合同对应b3de65b0两项新finding，所有新unit尚未执行。

新增实物driver设计映射（未运行）：FS01/02/03/04真实Seaweed旧版本+全11事实、typed transforms、empty及130行2文件3页；FS06/08独立query冷热及同页replay的父账delta、完整返回耗时/尾段/RSS；FS05/07本机TCP慢header/body/EOF、取消、更短父deadline及sealed坏源/晚重复拒绝并清连接。所有证据仍missing，不将sealed-v1叫作实际后端版本。

D1–D3修订映射（未运行）：FS05/07用独立wire V2/header+summary验证unsupported与损坏V1分类；FS09/08验证主因和二次identity/cleanup/log失败分别留档、case finally数字trace不丢；FS06实际第二GET准入后取消并记录请求/触发点/return/close，未进data阶段不得算取消通过。对应独审ec8340b0，原时间/内存/工作集预算不变。

当前候选含27项unit设计（reader13、codec9、driver证据5），新增wire V2分类与失败/取消证据修订均仅AST检查；尚未运行，不能依据候选代码标支持。

第二轮driver源审7777b208的先行修订：普通unit包入口也必须可导入driver，不依赖coverage脚本偶然附加的harnesslib路径；真实backend每个新query的实际刷新binding须在第一次read前保存canonical bytes/SHA/query_id及许可输入索引。每次已返回page/replay的wire与完整调用计时在验证断言前后均有独立journal，失败finally也保存已完成部分；upload时的旧fixture binding不能冒充当前query输入。补证据负例必须证明成本断言失败仍能关联实际binding与已返回page，不将unit mock当作S3或deadline通过。修订前当前20file/27unit仍未执行。

本轮修订后候选为28项unit（reader13/codec9/evidence6），新增成本断言失败仍保留实际binding/已返回page的负例设计。每query第一次read前落实际canonical binding和独立输入索引，每次read/replay在finally落wire+调用journal，case结束再归总；代码仅AST，28项仍未运行。


## 2026-10-21 首次本机组件结果

历史先行合同中的未运行状态按本段更新：原32项ordinary unit通过，新增6项边界unit单独通过；首轮完整Python coverage264项全通过但4451/4474、23行缺口、零排除，门禁明确FAIL。新6项针对signed BYTE/无效UTF8、转义JSON/非整数、ARROW辅助metadata、真实writer页CRC、授权异常与注入编码不收敛，新增测试后实际Python270项全通过，51个生产文件4474/4474、零缺口/零排除，python.json SHA4a851aca3bf769fa5483eb989419dde227dd43c6a5e72fc067ea10b6378c4038与3phase/result/identity在artifacts/p04-python-coverage-boundaries，前后源码身份一致；Rust严格100%与全任务仍待重验，不减少原用例或新增排除。

20文件ec182冻结、历史全树fd1b4947身份下，实际functional6/performance4/fault23全部通过，报告位于artifacts/p04-component-first/fixed-sources-{functional,performance,fault}/report.json，SHA分别d447f587f760e0605e1c838bcd85a20346b3e04b75d30af0c0ea9f4a83b5e22b/407ef10ead72769ca7cb992e900a5f6d713fce976978e217dce5fd81ebeae3b2/71472ecf1429e09d229064ec9ddcfd200658084e94f7d8e27f3e5d4adb9b6062。独立安全原始267文件2,018,773B/28wire与字面真值、metadata对象闭包、物理位置和账本审查e3f87325328694c803fa55e701bf17a3f81f7fae87c6d4b184fe845e336df773通过。最大page41.765ms/cohort63.335ms/逻辑1,903,748B/RSS102,612,992B；冷2/3 GET、暖0；第二GET后cancel全调用10.896ms/触发到返回2.849ms。原产品预算无改动。

范围限制：200ms parent用例为0GET前cleanup-slack拒绝，不认证网络等到到期；最终listener/threads/active均清零但无独立teardown总耗时。OS缓存未控、内存授权非PG、sealed-v1坏源非S3version、HTTP签名/原头无完整独立回放；无一般格式/生产规模/真实云/I1结论。后续shared5接线和本结果文档改变whole checkout，旧报告只绑定其历史身份。shared独审0455c58eb8e76913293844a905e6a97dcfb6f6d225164008955dccdcef18da31确认原全部argv/timeouts/states/900watchdog/100%/21豁免不变，只追加3driver与compileall；实际32ready命令17220秒加600余量17820秒297分钟，job300/release360。当前整项17d plan/check、正常hook、提交后报告、PR12依赖与本片PR/main/双CI仍pending，组件通过不结束任务。


## C3 真实目录与对象组合（实测前先行合同，历史状态）

可信 host 必须在 bind 前建立 ReadParent：同一个单调 T0、不可延长截止、取消和执行账。发行 binding 后仅允许一次 attach，host 上限与 binding 预算逐项取 min；对象、输出和 managed memory 保留同一 scope 累计账，唯一 CatalogReadControl 的 PG invoice 单列，不把 PG 请求计成对象 GET，不将嵌套耗时相加。

仅显式 ControlledAuthority 可调用网络重授权，与原内存 callback 入口互斥。每次 PG 操作取 query、parent、page、cohort 与原 5 秒上限的最小截止，回调返回后重新取时钟；分页不得覆盖或重启 query/cohort。保留原 1s/page、5s/cohort、250/200ms 余量及全部输入/输出/内存上限。

验收映射 C3-PARENT：普通 unit 验证 bind 前耗时、一次 attach、预算 min、fresh clock、页切换及 child deadline；C3-PAIR：真实 PG 发放身份后读固定双源11行（main10/mirror1）及130行（64/64/2），独立 PyArrow 真值、位置、重放和终页；C3-FAIL：撤权、PG pause/cancel、坏对象、COMMIT unknown、精确 pin 清理。先行时后两组尚未运行，当前结果见下节；原79 unit及 functional/performance/fault 三 mode 不以 pair 替代。

成功或失败均以实际 binding 精确 release；未知 bind 仅使用原完整 request close，found 必须 release，absence 仍 cleanup_unconfirmed，禁止 rebind。清理使用独立不超过5秒 control，费用单列且不恢复执行权。C1仅证明客户端返回和 FD close；远端 PG 停止、完整 server 费用和 native memory 仍缺失，不声明生产支持。


## C3 本机受控组合实测（2026-10-22，作者组件通过，独立证据审待结论）

第三轮显式 `--mode pair` 在固定 PG18/Seaweed3.97 本机镜像上实际完成8个正向组合与10个故障场景，原120秒外层/110秒软清理窗口未改，外层29.754秒。全11事实保持main10/mirror1，双源130保持main65/mirror65、分页64/64/2；普通与located各自冷暖、重放、终页拒绝及独立PyArrow物理回表均已执行。PG真实register/publish发放binding，执行不重签或替换其字节。

故障覆盖bind前耗时、目录撤grant后的下一页/缓存命中拒绝（既有目录合同精确`unauthorized`）、PG行锁、暂停后取消、COMMIT响应丢失的found/absence、真实GET后注入迟到/字节破坏；这两种对象注入明确不是远端服务停止证明。found精确release，absence保留`cleanup_unconfirmed`并拒绝rebind，不解释为durable closed。所有已发行pin精确清理，两个owned容器、两份日志和网络均确认释放，无HOLD。

作者报告 `artifacts/c3-pair-third/run/report.json` SHA256 `1c66ea25b4f6565a171465eea3d9f62aa5b2c55525a33b422b1dad7ed9196add`；安全证据索引 `artifacts/c3-pair-third/evidence-index.json` SHA256 `59583ad98dce6057a79f1721b88bfa061016466afbdd8a3530b9aa5ab2903504`，183个文件。该轮source19冻结清单`565d02b2`与完整76路径闭包前后完全一致；本段结果文档在实测后追加，不冒充该次已跑源码身份。最大实际page198.681ms、cohort338.523ms、managed逻辑峰值3,865,042B、外测RSS125,714,432B；只陈述本机组件观察，不能作为产品性能baseline。

前两轮FAIL完整保留：第一轮旧P04观察器把bind后剩余TTL错误加到C3的bind前T0；只新增pair观察器，保留实际T0/原parent截止/绝对wall映射，旧helper与原79单元不改。第二轮新fixture把撤grant的`unauthorized`误期待成epoch变化的`revoked`；普通最小复现确认既有语义后，仅修精确期望并保存expected/observed诊断。三轮闭包JSON实际路径数为75/76/76；此前口头73/74计数有误，以保全JSON为准。前两失败不是通过，第三轮也未抹去它们。

原P04普通79、对象26、目录39单元均已通过；定向parent/child/组合/启动留证单元另有日志。这些及本次pair不替代原functional/performance/fault三mode或完整原base门禁。独立证据审、strict coverage、整项原base check、正常hook/提交后验证、上游依赖/PR/远端CI/精确main仍未闭合；PG远端停止确认、完整server费用、PG/native内存、单故障域以外/真实云/HA/生产规模仍缺失，不能据此声明完整产品支持或可发布。
