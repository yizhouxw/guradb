# 变更计划：P04 固定源共同读取首片

## B2 私有 located 最小切片（文档先行，待实现/待验收）

沿原task4696/base17d/HEADb3dd，先保存B1精确30源0de、receipt和450份许可安全实物（不扫旧LLVM/314）到 `artifacts/p04-b2-source`，before manifest `75db9f5d88428355900532583b3645cf8944b6d360d4b074197153e19605eb7d`。B1已有非作者组件e8a78f02及ROOT资源释放，原外层工程FAIL、59bin补证与旧首失败均不重写；不是B2或完整任务结论。

依据8ee2方案、a727联合计费补文、P01 ee84/25d912定位验收清单，只新增私有 `fixed_source_located.py` 和reader的 `read_located_batch` 入口，共用加载/所有权/lifecycle。普通A的 `_batch/_encode` 保留；B2复用decode实际location并保存有界metadata定位范围。不可变LocatedBatch持原A Contract与封闭canonical `p04-located/1` bytes；P含context/batch SHA、ordinal/last和逐ID/version/cells SHA/RowLocator，不给consumer开放_state、不新增公共A或二套reader。

每页联合L≤768KiB/64行、原8MiB live/1s page/5s cohort/父TTL不抬。冻结其它Usage和原页表，D为本batch此前父真实output prefix，有限32轮求u=D+L(u)，固定64hex摘要重算；最终验证方程、A完整Contract/validate_batch_for、P闭形/canonical/一一摘要/实际source与对象/RG/offset。分配前同时预约A/P树、字节、哈希/Contract副本；完成所有构造/检查后fresh auth+clock/cancel及预算检查，一次delivered(L)，之后只返回既有值。不足整页失败，不缩页、不退款、不重复加D，不在已经成功read_batch之后补P。

文件域只追加三leaf、reader/职责helper、独立located unit/fixtureconsumer与既有acceptance/backend/fault叶子；每源≤600，原65单位/10/8/26/物理输入及预算保留。真实consumer用独立PyArrow实际按locator回表，核P01全11与双源130/重放/版本/完整父账，负例含hash/定位/联合cap/内存/最终撤权取消/后源损坏。先SOURCE冻结非作者必要复核，再获独占窗首次验证；当前禁止import/测试/formatter/服务/Cargo。P06单源/processing manifest对象闭包/共同账、C控制、PG/Rust/IPC/I1不在本片偷补。

SOURCE候选仅定义：原65加located14项共79 unit；functional保留10并另列4个located cold/warm，performance保留8并另列4个located，fault保留26再追加2个located拒绝为28。独立consumer实际按每条固定locator回表；新JSON/P wire/journal在任何断言前留档。所有新增定义/driver仍待非作者SOURCE审查和首次运行，旧原件不填新结果。

## B1 双来源行为切片（文档先行；源码候选/待验收）

沿原 active receipt `4696bbe16be041d3b900019fe2fd08b3`、base17d、HEADb3dd，不缩任务范围、不提交或重写失败。行为前完整保存已验收源28（`51601127`）、receipt 与 314 份许可安全原件/三报告到 `artifacts/p04-b1-source/before28`，before manifest `e42ae809c399c70ae785641a99e77907404c374e837a3a381860377eb4a14d53`。本节先于行为；SDK single-source 配对报告只保留其精确历史 claim。

唯一行为范围是 connectors reader/manifest/职责 input helper、fixture/acceptance/backend/fault 增量和新 multisource unit；三 leaf 同步合同。复用原 decode/FixedObjects/SourceScope/分页，不复制 reader；ROOT 共享 kit/harness、P03 七生产、A/锁/预算、旧 44 unit 与原 6/4/23 样本不动。fixture refresh 必须同步所有来源保护期而不重绑在途 query，单源默认输入/期望保留；真实 driver 只追加双源 cold/warm 与独立来源/位置真值。

冻结 1–2 个 manifest/1 来源，先读全 metadata，校验联合精确对象闭包、所有字段/schema/身份策略和总量，再完整 scan/全局唯一 ID/排序后分页。main10+mirror1 必须两个实际 metadata/Parquet，`source-main→p04-main-v2`、`source-mirror→p04-mirror-v2`，P01 视图版本不冒充物理源。保留 A 的全局 revision_version 规则；若任一来源声明 derived version，全部返回行仍须符合 A 验证，不另造局部版本语义。

联合预算不增：Σmetadata64KiB、Σdata4files/4MiB、单file1MiB、Σ16RG/1000rows、32fields、同时 live8MiB、64rows/768KiB 页、1s/page、原5s cohort，父 TTL/权限/预算更小优先。原 query/ledger/batch锁/全局 seen/order/ordinal 唯一，所有同时 live metadata/decoded/state/输出副本预约；第二来源的损坏/重复/超限/取消不得留下部分成功或退款。新增真正负例，不改旧断言消回归。B2 located API 与 P06 processing/计量交接不在本片实现。

先 SOURCE 冻结交 ROOT/P01 非作者复核，再独占窗首次新增/全部旧 unit 与既有三个 CLI fresh 验证；当前没有运行/formatter/import/服务/Cargo 权限。任何首次失败原样保存，不改负载/上限/样本补绿；完整任务、PR/main、M/P/I1 仍待后续验收。

新增源级分页补证先行：保留单源 130 行，同时独立构造双源 main65/mirror65 的两个真实 metadata/Parquet，真实 cold/warm 核全局页 64/64/2、ordinal/last/同页重放/完整 ID-version/定位/同父账，仍在原 caps 内，不替代 full11 来源义务。字段32明确计 Resource≤32 且Σ所有来源完整 schema字段≤32；metadata 解析有原有界预约，联合计数通过前不分配 data/记录工作集。

源码候选收尾：新增职责 helper `fixed_source_inputs.py` 统一 metadata 预检、精确对象闭包和联合上限；reader 只改首次加载循环，页/封套/授权提交沿原实现。独立 fixture 真实重写 mirror physical IDs 为201–206，并保存其 source/version/locator，不能只改 metadata。原44 unit 完整文件不变，新增21项定义，三个 driver 仅追加为10/8/26；所有 B1 定义尚未执行。SOURCE 静态核对不代替非作者审查、首次 pure units、三个真实 CLI 或严格覆盖与完整原始任务门禁。

### B1 首验失败与期限oracle窄修（测试修改前）

ROOT首次run `artifacts/p04-b1-real-once/first-20261021T1617` 完整65 unit：64通过/1失败，unit内0.726s、外层1.1165103s，原30源未变；functional/performance/fault均未启动。失败仅在新增 `test_two_real_manifests_full11_origins_fields_and_single_ledger` 的started/deadline tuple严格相等断言，deadline从860901.5909262081合法收紧到860901.590023875。生产 `ReadScope.check` 原本取min(old,monotonic+wall剩余)，实时双时钟采样不能保证绝对不变，属于新增测试oracle错误，不是生产延长或退款。

修订前完整30与当前40份失败原件已保存在 `artifacts/p04-b1-source/deadline-oracle-repair`，before manifest `b6d2b9b4c89b216b8390da1471aaec6afef80e4712310bbc196d812ebd065e5a`。先写此三leaf，再只改该新增函数：确定wall=bound_at、monotonic=0；保留原started/deadline相等断言，追加wall前进1ms但monotonic不动的同页重放，核deadline严格减1ms、原started/同parent与0新IO/真实输出累计不重置。原44完整文件、21新定义数、生产/预算/driver均不动。SOURCE增审后才复验，无盲重跑；失败run保持FAIL。

首次runner还观察到默认bridge网络ID变化，containers空且volumes相同；该外部资源差异仍HOLD由ROOT独立只读事件对账，不把测试修订或源码冻结当作清理证明。

## 当前配对 A：direct 夹具与环境证据（行为修改前）

本轮承接 active task `4696bbe16be041d3b900019fe2fd08b3`，原 base `17d66c66a067eebe73280ce8d3488fb4f7cdcfe9`、当前 HEAD `b3dd39f68511558d86753f3148e1b9731bcde622`。行为前逐字节核对既有 26 源冻结 `f42f5f29dcad79e346c43ad4ce00eab9923ff0b0eddd76a87f75a80eae9e0fd0`，在本树 ignored `artifacts/p04-direct-fixture-source/before-26` 保留完整原件、receipt 和状态。历史 6/4/23 三报告与旧失败保留，不复用为本轮通过。

最小改动仅为三份 leaf 文档、P04 fixture/acceptance 叶子与必要纯 unit：显式请求 `Lab.s3(direct=True)`，在 P04 专有上传前校验 `Config.proxies == {}`、三份锁对应 SDK 实际版本及实际镜像安全摘要。ROOT 唯一拥有共享 `scripts/m0lib/kit.py`，机械合入已审的 opt-in direct 与 `s3_certification` 六字段；默认 `direct=False` 行为保持原文。叶子不复制 SDK、P03 dot 审计或生产读取语义；镜像实际 ID/OS/architecture 为观察值，固定 index 引用不变，不将其虚称为 child/config attestation。

生产 P03 七文件、P04 六文件、固定输入、6 功能/4 性能/23 故障、38 既有 unit、原 CLI/预算/锁/门禁均不改。SDK setup/upload 与真实 P03 显式 RecordingProxy 读取分域记录；此前 no-ambient 声明不覆盖旧 SDK。新增 unit 只认证 direct 调用/安全摘录/错误前提拒绝，真实 SDK/S3/跨平台必须后续 fresh 三 driver 验证。无新 runner；SOURCE 冻结交 ROOT/P01 独审后才排独占运行窗，当前没有运行授权。真实 PG、native/RSS 硬界、完整门禁、M/P 与 I1 仍 pending。

叶子证书在 Lab 原有 readiness/bucket/基础对象 setup 之后、P04 专有上传之前；保持该先后关系，不虚称 SDK 操作尚未发生。SDK client 的独立 close 未单独认证，本轮不扩大生命周期重构；独立进程与 owned 服务清理不等于全部 SDK lifecycle 通过。

状态：先行合同，尚未实现或执行。Git 原始基点17d66c66a067eebe73280ce8d3488fb4f7cdcfe9；branch codex/p04-fixed-source；worktree /Users/chad/dev/guradb-p04-fixed-source。起始树干净；task713da24750d74cd2b53be5679fd184ae，checkpoint checkpoints/20261021T051951Z-before-p04-fixed-source-f28afd4e；作者/hook沿本项目配置，不沿用别仓约定。

## 目标和范围

落实并行计划 P04/W1b 的固定 manifest SourceReadPort 子片。依赖主线 CF1-A/P01 与 P03 固定对象读；P03 当前候选源码与真实局部证据已有，完整交付仍进行中。可先建立源合同与 reader 实现，真实 P03 配对和正式门禁必须等待其可验收实物，不以 fake 数据通过代替。手册与场景先于行为见[用户合同](../user/fixed-sources.md)、[场景表](fixed-sources-scenarios.md)。

root独占 modules/connectors/fixed_*.py、tests/unit/test_fixed_sources*.py、tests/source_support/、scripts/fixed_sources_acceptance.py 和本片三文档；用户 README、harness 选择/命令及 architecture 仍由 root 串行处理。禁止改已有 Iceberg/incremental/writer/training、Rust旧reader、common/A、P03/P06 生产模块、依赖锁或覆盖政策。每源文件至多600行，connectors只依赖common/storage。

白名单：一个固定 manifest/1、flat text/int8/bool、明确物理 field ID、A 三种变换、完整 Resource schema、确定性最多64行且编码有界分页、强完整性对象和共享查询预算。Iceberg/delete/schema演进/append/writer/保留维护/B-L/训练均不在首片；本包不因此整体完成，也不证明 I1。

## 私有 metadata 候选和不变量

拟议 canonical UTF-8 JSON p04-fixed/1，关闭字段集合：manifest_version、source_id、source_version_id、snapshot_id、source_schema、files、delete_files、schema_evolution。source_schema逐字段保存source_field_id/name/type/nullable；其完整数组canonical摘要必须等SourceVersion.source_schema_sha256，实际Parquet完整schema按ID/type/nullable核对，不只看投影列。files每项包含完整ObjectRef与各row_group_rows；实际footer的组数/每组行数须一致，总覆盖来源于冻结metadata全枚举，不用最后一个batch自证。delete_files必须空，schema_evolution必须none，未知语义拒绝。

metadata与数据对象必须分别属于同一固定revision，读取经共同ObjectReadPort/P03，无直接socket/SDK/本地路径捷径。SourceVersion.resource_schema_sha256与Resource一致，映射不得缺目标字段。key_v1复用现有common算法，派生版本为固定revision ID；无复合键/隐式转换。全输入唯一ID检验完成前不宣称整视图完整。保留逐行实际文件/组/偏移供独立核对和后续B-L设计，只暴露A SourceReadPort。

不变量 INV-001/002/005/007/008/010/011/012；遵循ADR0004/0007/0016/0019/0020与connectors AGENTS。固定schema、snapshot、版本、read binding摘要、授权epoch不跟随latest；source物理顺序与逻辑排序分开。分页重放不重复授权身份，但真实请求/输出仍累计，跨binding缓存不得偷换context。

## 实现前必须解决的风险

1. 共享预算：A ObjectReadPort只返回bytes，不能推断其真实重试/缓存/请求成本。构造器必须接同一可信查询计量owner的快照/预算接口；先检查P03实际可用scope，禁止重新做一套storage客户端或凭借文件数生成Usage。该接口接线需独立复核。
2. 原生解码：PyArrow/Parquet的native分配和同步decode不能用返回后的nbytes/时钟检查证明可抢占。先核锁定API与可中止、可清理的隔离办法，证明预留覆盖所有同时存活bytes/Arrow/typed rows/encoded output。不能证明时收缩为明确拒绝，不开放看似有预算的路径。
3. 首片有界全量排序至多1000行，不是P10的生产按需provider或规模证据。分页顺序稳定不能丢失真实物理locator；不预先冻结尚未评审B-L。
4. 当前授权callback本机有界不等于实际PG链路；PG原期限/取消配对留P10/P13实际验收，不继承默认5秒目录deadline。

## 切片、恢复和文档先行

先保存本三文档/用户导航的docs-first diff与摘要，再跑拟议文件plan。随后按codec/字段映射、共享scope、解码/排序分页、独立fixture和真实driver拆小职责。每次源码修订独立review后受控窗口运行；不与其它性能/故障/coverage重叠。真实PG或P03实物依赖未齐时继续源码，缺少证据不标通过。

无源/目录格式迁移和用户数据写入。新私有格式未知即拒绝；旧reader行为不变。失败保存完整含untracked diff、原命令、input/seed/trace、服务清理及当前假设；用本checkpoint在新目录恢复，原现场保留。代码恢复不撤销外部写/租约，目录query pin由可信owner清理。两次无新证据失败停止盲跑并定位根因。

## 验证合同

固定P01 view-v2的11条可见事实、int8边界/NULL、物理IDs101–106到Resource1–6、重排三row group及独立key/版本真值；另认证empty源/多文件与多页，或明确保持不支持。footer/schema由独立PyArrow reader核，期望集合来自P01/手核，不能由被测reader生成；真值全量而非只top-k。

负例含错schema摘要、物理ID/name/type/nullable、未知字段/版本/delete、错snapshot/缺对象/坏checksum/短读、重复/null/过长ID、派生版本、int8损失、跨context分页、revoked/cancel/预算、原生decode故障与清理。manifest/data GET和retries缓存真实计量，不缩原输入或换暖缓存。范围/成本预算按用户合同：64KiB metadata、4x1MiB input、16groups/1000rows、8MiB工作集、64rows/page、5s cohort/1s page/512MiB RSS；context更小优先。运行raw记录实际环境/镜像/源码/锁/输入/配置和前后身份，失败finally仍留证清理。

最终以原17d完整plan选择门禁，初检、正常hook、postcommit检查、task-finish/显式raw归档、当前PR双Python CI、expected-head merge、精确main check/checkpoint与双main CI全部闭合；不借旧M0/P01/P03结果补本片。新增3driver时root按当前实际main命令重新算CI预算，保留900watchdog/strict100%/原21豁免及planned full gates missing。

## 当前证据

已建立clean原17d task713da247、checkpoint051951，先行文档后编写6个生产候选和20项unit设计。R3十四文件源码冻结42fb0147的独立审查ffbd8cee通过，14文件前后摘要未变；这只证明源码准入，不证明20项测试、Parquet互操作或预算已经通过。尚无imports、运行报告或正式门禁，P03仍未进入此片基树，禁止临时跨checkout import补证据。

新增scripts/fixed_sources_acceptance.py与3个source_support driver helper为源码候选。functional/performance拟用真实Seaweed versioning，对每个输入先写固定版本、再覆盖最新版本，P03仍读取原精确VersionId；固定11事实、多文件130行/三页、空源及typed key/derived version分别核独立writer/reader真值。每query独立scope，共享256KiB cache的冷热必须公开，完整read_batch外层计时记录真实return/观察点/尾段、父账delta、wire及RSS。fault拟使用真实本机TCP注入和独立sealed-v1坏源，明确不冒充S3版本认证；deadline/cancel后必须无ReadBatch且服务连接清零。Lab的auth/s3配置和原始服务日志只写artifacts/private/，正式run目录仅保存白名单合成源、binding、数字trace和摘要，不能整目录拷Lab进CI上传树。

driver与unit均尚未执行；压缩/字典/page-v2、恶意metadata/Parquet、晚file重复ID、内存/请求/输出、原更短期限等负例仍missing。后续先独立源码审查，P03依赖闭合后在受控窗口实际运行，首次失败原样保存，不提高预算。当前14文件独审不覆盖后续driver，最终冻结将包含新增文件与结果文档。

## 机制选择与额外先行约束（行为前）

P01独立先行审查9b8f9ae8确认四个准入缺口：P03计量不是只读snapshot、batch费用不能重复累计或peak作差、native解码不能后置限额、64x32 text可能超过A envelope。为保留原8MiB工作集/1s page/5s cohort/512MiB RSS预算，首片收紧到无压缩/无字典DataPageV1的纯Python受限解码，详见手册新增合同；不复用现有Rust/PyArrow先解码后nbytes路径，不声称native机制已认证。此举不更改共同A或既有reader支持范围。

事实依据为Apache官方[Parquet thrift结构](https://github.com/apache/parquet-format/blob/master/src/main/thrift/parquet.thrift)、[data pages](https://parquet.apache.org/docs/file-format/data-pages/)与[encodings](https://parquet.apache.org/docs/file-format/data-pages/encodings/)，以及[Thrift Compact Protocol](https://github.com/apache/thrift/blob/master/doc/specs/thrift-compact-protocol.md)。按规范独立实现窄解码，不复制参考代码。footer<=64KiB，Compact总nodes<=4096/depth<=12/每container<=1024，字符串先核长度，Thrift i64仅至多10B的64位ZigZag varint（PLAIN INT64仍8B little-endian），page/chunk范围/数量和实际消费闭合，单步scopecheck；schema最多32字段、16groups/1000rows与既定对象上限不变。解码行和值额外预留包括Python容器保守开销，不按返回后nbytes声称预留；不足时先拒绝，即使各独立最大值未超仍可能联合预算拒绝。最终独立审查必须核预留上界，不凭常数存在视为证明。

SourceReadPort构造器须接同一P03对象reader与scope（绑定摘要/对象port身份防串接），当前authority reauthorize callback有界内存；真实PG仍missing。内部object输出+最终batch双口径保守收费；每次局部memory峰值含先前retained不为0，counter delta与父账和重放实际工作核对。完整ReadBatch envelope上限768KiB，确定性row边界预先保守留足Usage/封套字段，按固定row编码成本确定边界；全输入验证前不交页。source_schema按ID升序canonical、完整物理schema按ID比较，单文件内columnchunk顺序仍必须符合其自身footer schema。

新增负例：压缩/字典/页v2/嵌套/未知logical annotation/encryption/external chunk/index；恶意Compact长度/深度/节点/重复字段/截断/整数溢出；page run展开超过剩余行、坏UTF8、超4096字符/ID不合法；超大合法单行/字节缩页；第二page活跃memory非0、重放实际IO正确delta、scope锁不嵌套；即使损坏在后file/group也零页输出。原生decode风险通过明确拒绝该路径收敛，不是假测native取消。当前仍无新源码/运行。

独立机制复核补充：revision.objects完整集合恰等metadata+files、empty仅metadata；此私有窄语义先拒绝额外对象，不猜漏读。SourceScope从组合根一开始继承ReadScope并与FixedObjects同一实例，override reserve仅在父Reservation成功enter后观测本batch peak、keep/exit原义不变；batch开始以memory_current初始化峰值，counter前后delta。自己的batch lock不嵌套P03 operation lock；batch期间其它thread直接port操作拒绝。check先调用super保留原querywall/mono/cancel，再核首次batch固定5s cohort与当前1s page，不修改父deadline；P03既有5ms monitor动态dispatch check并传200ms slack，故保留该清理余量。所有源码路径须逐步调用check，不能只依赖I/O monitor。output envelope自含Usage长度按固定上界准入，最终重授权/扣账/编码先后与实际len需在实现独审确认。此为候选接线，非实际测量。

## R1源码独审后修订（行为修改前）

首版6生产源码+4docs冻结ba4871e8，独立源审06071321指出两项P2：过早取Usage.elapsed遗漏首次完整封套构造/验证，输出失败仅poison但仍持有_state缓存。本轮不改共同A/原预算：先正常完成一轮Contract+validate_batch_for+当前reauth，再观察真实delta，最终再次正常构造/校验/reauth/实际输出扣账；不伪造validated对象或移走首次scan。不可变封套仍有最后观察后的尾段，必须由外层真实page_elapsed及last observation/return/finalization_tail数值明确计量，Usage.elapsed只陈述最后观察点，不伪称精确结束时长。原1s/5s/父deadline实际覆盖终次构造和清理；若真实尾段超预算原样FAIL，不抬预算。失败时_state与本reader缓存清引用，父scope累计账/P03输入不退款，fresh scope才可重试。新增负例在首次scan已成功而最终授权/输出失败后核_state为空、后续expired_context及父账仍保留。

这段在R2生产修订前保存；先前R1无imports/runtime，新增独立PyArrow fixture及7项reader unit仅为源码候选，尚未运行。P03依赖尚未进入当前P04基树，不借其它目录临时import宣称通过。

## R2独审后的所有权与输出提交修订（源码修改前）

R2十三文件0a8229f独立审查b3de65b0确认前两问题正常单owner路径已修，另发现P1同reader并发未得scope锁的拒绝会清在途T1的共享_state，以及P2最终delivered后再check可拒绝但已记成功输出。R3先建立每reader非阻塞锁，未取得reader所有权的拒绝在清理try之外；成功owner的所有参数/scope准入/解码/输出错误仍统一清自身_state，finally释放reader锁。source的scope batch锁及P03 operation锁原义不变；不得让T2清T1缓存。

所有可拒绝观测/keep/授权/构造准备移到最终scope.delivered前，保留delivered自己的最后check，提交后不再作应用策略检查。内部只称precommit时间，真实返回/完整finalization_tail由外层实测。新增两线程Event负例验证T2拒绝而T1返回正确集合、state不poison；新增输出提交点的取消边界验证不出现已计成功后再本方法拒绝。只unit用可控clock/Event，不将它当实际1s/5s并发或网络证据。原预算/共同A/完整实物driver义务不变。

## driver R1独审后的先行修订合同

十八文件aef197独立源码审查ec8340b0发现三项阻断。D1：现codec在合法V2的encoding_stats/header先抛corrupt而非合同unsupported；先核通用wire类型，再明确拒绝非V1 page/summary，不改变合法输入范围或负例期待。独立手写V2 header（不带summary）和summary断言覆盖两个入口，损坏V1仍corrupt。D2：driver成功后才写lifecycle、case return后才保存数字观察，失败和二次identity异常可能丢主因；改为finally保存安全observations、owned清理/log rc、privateLab位置和分别记录primary/identity错误，禁止为收证吞掉失败或把未完成清理标通过。D3：取消timer早于reader/证据保存，改为外部thread等实际数据第二GET到达才取消并持久触发/请求/返回点，真实未到数据阶段须失败。以上先记录再改源码，原预算、测试负例、真实端依赖不变；R3/driverR1审查保留历史，均无实际测试结果。

D1–D3修订后的候选状态：已按先行合同修改2个codec入口并保留V2拒绝期待，新增2项独立wire/summary负例；driver的safe证据helper、所有case finally观察、成功/失败Lab清理与network probe、二次identity错误和最早cause分别记录。数据取消watcher只在server实际观察第2GET后触发，返回必须核触发点/请求数/worker退出；没有到达即不能通过。另新增5项synthetic生命周期负例设计（import+identity双故障、body/cleanup链、log失败、artifact失败cleanup），只证明证据流程。当前共27项unit设计（reader13/codec9/evidence5），全部只AST未运行；R3的20项源审与本次新增driver审查范围分别记录，待新全源独立审查，不抬任何预算。

第二轮driver源审7777b208的先行修订：普通unit包入口也必须可导入driver，不依赖coverage脚本偶然附加的harnesslib路径；真实backend每个新query的实际刷新binding须在第一次read前保存canonical bytes/SHA/query_id及许可输入索引。每次已返回page/replay的wire与完整调用计时在验证断言前后均有独立journal，失败finally也保存已完成部分；upload时的旧fixture binding不能冒充当前query输入。补证据负例必须证明成本断言失败仍能关联实际binding与已返回page，不将unit mock当作S3或deadline通过。修订前当前20file/27unit仍未执行。

本轮修订后候选为28项unit（reader13/codec9/evidence6），新增成本断言失败仍保留实际binding/已返回page的负例设计。每query第一次read前落实际canonical binding和独立输入索引，每次read/replay在finally落wire+调用journal，case结束再归总；代码仅AST，28项仍未运行。


## 已提交对象依赖的接续状态（2026-10-21）

原713任务的20份候选源码及完整patch已保全；新目录 `/Users/chad/dev/guradb-p04-fixed-source-p03`、分支 `codex/p04-fixed-source-p03` 的任务 `4696bbe16be041d3b900019fe2fd08b3` 在clean原始 `17d66c66a067eebe73280ce8d3488fb4f7cdcfe9` 上启动后，才clean FF到已通过原4d完整post及独立审查的P03提交 `b3dd39f68511558d86753f3148e1b9731bcde622`。十九非shared文件先精确传递，随后root仅合成手册导航并追加本状态；原始范围仍为17d，不能改到P03或最新main。旧713仅在实际完整传递核验后abandon，旧dirty/raw不删除、不称完成。

采用已提交依赖的原因是让首次真实unit/Parquet互操作在同一checkout消费实际P03，避免临时跨树导入。P03 [PR12](https://github.com/yizhouxw/guradb/pull/12) 的当前测试合并CI及精确main验收仍pending；本地依赖准入不冒充上游主线交付。下游正式PR目标始终main、blocked-by P03：先完成P03 PR与精确main/双main CI，再在正常提交的clean下游分支同步最新main，并按原17d完整复验后才可合入P04。

28项unit仍只有AST计数，六功能/四性能/23故障case尚未实际运行；原SOURCE审查不是运行通过。新独立venv、普通unit、三driver、shared selector/compileall/CI预算接线及完整门禁另排独占窗口。新增三driver按原timeout需要至少297分钟工程job预算，root接线采用300分钟且保留release360、600秒余量、900工具watchdog及全部产品预算/100%覆盖/原21行排除；最终以实际matching plan重算，不手填32条为已执行结果。


### 首次unit失败与窄修复（待复验）

`artifacts/p04-python-setup-unit/unit-first/result.json`（SHA412778881d29f0899187d85f8432e74e3c2cfe9aae43e4d2739802ceb1f19c10）实际28项中17通过、4失败/7错误；共同第一阻断为PyArrow22列元数据field16 SizeStatistics被白名单拒绝，并非取消/身份已测失败。未盲重跑。窄诊断保留2366字节真实Parquet及完整Compact树（diagnosis SHA9047024a9038f25805d32948ba3f772c73f7cf03d743445a81de543502feff1e），每列实际field16为struct，平面histogram有空数组和合法NULL/非NULL计数。依据[Apache Parquet thrift定义](https://raw.githubusercontent.com/apache/parquet-format/master/src/main/thrift/parquet.thrift)的ColumnMetaData16/SizeStatistics1–3，先补用户合同，再严格有界验证并与真实解码值交叉核验；不静默忽略未知字段、不减少原28用例、不改writer负载/预算。新增独立结构/手工wire负例与原真实PyArrow11行正例一起验证，修复前五文件完整副本保留。


第二次31unit结果b5067f1b90bbc6552ac59c8f3bd72be3ea0115e05a6a2f4426e35e3ca175b768：新增3统计方法通过，旧Reader已越过ColumnMetaData16，推进到DataPageHeader5可选空Statistics被拒绝的新阻断。对**同一已保留**2366B实际Parquet再解析完整页头，diagnosis817210f030f5f6fb16c6f12871bae828b743b424bb194a7c4b2d8d70d80e1fa7证明18个页的该字段为空struct；无重复reader/网络尝试。按Apache DataPageHeader5定义仅准入空struct；非空统计继续unsupported、错wire仍corrupt。补手写V1完整wire的empty成功/nonempty拒绝/wrongtype拒绝，同保留原28及SizeStatistics3方法一起复验。两轮首失败、输入和源码副本均保留，不为绿改writer或阈值。


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
