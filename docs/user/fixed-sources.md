# 固定 manifest / Parquet 源开发验证

## 当前 B2：同页记录与实际定位联合交付（待实现、待验证）

拟新增 connectors 私有 `reader.read_located_batch(binding, ordinal)`，返回不可变 `LocatedBatch`：原 CF1-A `batch` 与 `provenance_encoded` 两份已拥有字节。侧车是封闭 canonical `p04-located/1`，固定 context/batch SHA、ordinal/last；每条记录按同页顺序包含 ID、version、cells SHA 和原 A RowLocator（source_version_id、完整 ObjectRef、row_group、row_offset）。定位来自实际解码，不能从排序/ordinal猜测；消费者只读取该出口，按固定版本实际回表验证，不读 reader 私有 state。定位是数据提示，不建立权限或独立事实来源。

两份输出合计仍≤原768KiB、≤64行，保持 B1 既定页表，超限整页拒绝，不拆页/截断。共同父账令D为本页此前已交付的对象输出，L为A+P实际字节，A.Usage.output_bytes=u满足u=D+L(u)；最多32轮、safe integer与最终方程/hash/locator均验证，不能重复收费D。所有临时树/字节/Contract副本在原8MiB内预留，最后重新授权并重读时钟/取消后唯一delivered(L)，失败无A/P交付且原费用不退款。普通 `read_batch` A路径和原预算保持。

B1精确30源0de已完成本机65 unit与真实10/8/26组件配对；其外层工程FAIL与补证原件保留，不充当B2通过。B2另验完整main10+mirror1与双源130的64/64/2页、冷暖/重放/真实PyArrow回表，以及联合cap、错误定位/hash、撤权/取消/坏后源负例。当前仅同进程私有出口，不认证IPC帧、公共B-L、P06对象闭包/父账、PG、Rust或I1。

## 当前 B1：同一固定视图的双来源读取（源码候选、待验证）

B1 拟将本机窄 reader 白名单扩为同一 binding 下 1 或 2 个 `p04-fixed/1` manifest SourceVersion。完整 P01 view-v2 必须实写两个 metadata/Parquet：`source-main` 的 10 条与 `source-mirror` 的 1 条，分别固定版本 `p04-main-v2/p04-mirror-v2`；保留原逻辑 ID/version、NULL/int8 及逐源完整字段 ID 映射，不能用一个 SourceVersion 装 11 条或按标题/cluster 去重冒称多源。P01 `source-v1/v2` 是视图版本，另留显式来源映射。

所有来源共用原 binding、FixedObjects、SourceScope、原父账本、全局唯一 ID 检查/排序/ordinal；读取全部 metadata 后先核联合范围，再解码 data，全部验证完成前无页输出。联合上限保持 metadata 总 64KiB、4 个 data 文件/累计 4MiB、每文件 1MiB、16 row groups、1000 行、32 字段、同时 live 8MiB、64 行/768KiB 页、1 秒页与原 5 秒 cohort；父 TTL/授权/预算更小优先。不是每源各给一份预算，失败不退款或返回前源部分成功。

保留原 44 项 unit 与 6 功能/4 性能/23 故障样本，另加双源 cold/warm 和第二源损坏、跨源重复 ID/错字段、联合超限、超过两源、晚撤权/取消等负例。全部新页的逻辑值与来源/版本/位置须核独立 PyArrow 真值，每 query 零重绑定、镜像 1 条零遗漏。B2 located 公共或私有出口本片不实现，不改 A/生产 P03/SDK kit/旧预算；真实 PG、P04→P06、M/P 与 I1 仍未认证。

另追加真实双源 130 行（main65/mirror65、两 metadata/两 Parquet）的冷暖 cohort：全局页必须为 64/64/2，ordinal 0/1/2、last/replay/ID-version/物理位置及同一父账核独立真值，不能借旧单源 130 行样本代验。字段上限具体为 Resource 宽度≤32，且所有来源完整 source_schema 的字段数之和≤32；联合预检在 data I/O/记录工作集分配前执行，不是每源各给 32。

前一单源配对的 28 源 `51601127` 已完成 44 unit 与真实 6/4/23 三 driver，原件完整保存在 `artifacts/p04-b1-source/before28`；它只证明该精确历史源码，本轮 B1 全部待 fresh 验证。下列 SDK direct 与单源记录保留历史先后关系。

B1 当前仅完成源码候选：原 44 unit 逐字保留，新增 21 项定义；真实 driver 保留原 6/4/23，另加 full11 与双源130各冷暖两样本、三个跨源故障，拟为 10/8/26。尚未 import、执行测试或运行服务，不能把定义数量或先前单源报告当成本轮通过。

B1 首验记录：冻结30源 `492740ca` 的65项 unit 实际64通过/1失败（unit内0.726s、外层1.1165s）；三个真实CLI均未启动。唯一失败是新增同父期限测试用实时wall/monotonic却要求deadline绝对相等；现有父scope规则允许保持或收紧，不能延长。修订先保留完整原30/失败原件，再只在该新测试注入确定时钟，保留相等断言并追加wall前进1ms时期限严格收紧1ms的重放断言；尚待复验，不改生产或预算。原Docker默认bridge ID变化仍由ROOT独立对账，不能由测试修订消账。

## 当前配对修订：SDK direct 夹具（待实现、待验证）

本轮只修正开发夹具的 SDK 传输前提：functional/performance 的 Seaweed 初始化与固定版本上传须显式使用 `Lab.s3(direct=True)`，实际 client 的 `Config.proxies` 必须为 `{}`。该声明不改变 P03 自研读取 socket 经显式数字 loopback RecordingProxy 的路径；此前报告中的“no ambient proxy”不能扩展到当时未配置 direct 的 SDK。fault 的真实 TCP 注入不使用 SDK，仍单独记录。

新报告须在 P04 专有 manifest/Parquet 上传前记录并核验锁定 SDK 实际版本（boto3 1.40.56、botocore 1.40.76、urllib3 2.8.0）、direct profile，以及 owned Seaweed 实际 inspect 的六项安全摘要：`requested_image/image_id/container_image_id/os/architecture/repo_digests`。固定多架构 Seaweed 3.97 index 引用保持不变；不硬编码当前主机架构或旧 image ID，不将 Docker 返回的 image ID 称作 config/child manifest attestation。不能确认这些前提即失败；公开报告不含代理地址、endpoint、凭据、Config.Env、完整 inspect 或 SDK 异常响应。

Lab 原有 readiness、bucket 和基础对象初始化仍属于 setup，发生在这份 P04 叶子证书之前；本片不新增全 SDK 生命周期认证。独立 SDK client.close 尚未单独验证，当前 driver 为独立进程并由 Lab 清理 owned 服务；生产 P03 的 scope/连接清理仍按原证据单独验收。

本轮不改生产 reader/decoder、独立 PyArrow 真值、完整输入或预算。原 6 功能、4 性能、23 故障样本和 38 项既有 unit 全部保留；沿用下列三个 CLI，修订源码须重新执行，旧报告仅为历史证据。待 SOURCE 独审后先验真实 P03→P04 配对，不等待 PG/Rust/index，也不据此宣称 M/P、完整门禁或 I1 已完成。下文的实测状态仅适用于其精确历史源码身份。

状态：本机受限组件已实测，完整任务与主线验收待完成。本页面向模块开发者，不新增 SQL、HTTP、导入或源写入入口；旧 alpha 的源适配仍按原手册操作。

## 场景和操作

目标是对同一已发布、受保护 ReadBinding 读取一个固定 manifest 源，核对实际 Parquet 的物理 field ID、类型和 nullability，执行声明的字段与身份变换，按共同 SourceReadPort 返回完整 Resource schema 的 ReadBatch。逻辑记录 ID 和版本来自源字段或明确的变换，不由文件顺序、物理 rowid 或分页序号生成。

前置为 Python 3.11+、三份锁定开发依赖、CF1-A/1.0 和 P01 synthetic fixture。真实本机对象读取验收依赖 P03 的已验收实现；可信本地授权回调不代表 PG、P10/P13 或 I1 接线已经通过。以下命令已完成首次同checkout P03配对的本机组件验证；上游PR与完整门禁尚未闭合，不作为产品发布认证：

    .venv/bin/python scripts/fixed_sources_acceptance.py --mode functional --run-dir artifacts/fixed-sources/functional
    .venv/bin/python scripts/fixed_sources_acceptance.py --mode performance --run-dir artifacts/fixed-sources/performance
    .venv/bin/python scripts/fixed_sources_acceptance.py --mode fault --run-dir artifacts/fixed-sources/fault

每次使用新目录，预期记录真实 manifest、Parquet、固定 binding、源码/输入/配置摘要、实际分页和独立真值。文件存在、单元 mock 或旧 M0/M1 通过不代替该证据。

## 拟议支持与拒绝范围

首片仅一个 manifest/1 源，使用私有 p04-fixed/1 metadata codec。元数据必须与 SourceVersion 的 source ID、source version、snapshot、完整 source schema 摘要精确匹配；每个数据 ObjectRef 必须属于同一固定 revision，包含精确后端、bucket、key、version、size 和完整性语义。禁止 latest 查找、猜测文件名或按目录枚举补数据。

仅 flat text/int8/bool，int8 保留完整有符号 64 位值并按 A 的十进制字符串输出，NULL 与空字符串/false/0 分开。执行 identity、既有 key_v1 类型化长度前缀、revision_version 三种声明变换；派生版本必须是该 DataRevision ID，不能假装读取不存在的物理版本列。物理 source field ID 与 Resource field ID 可不同，字段重排不能靠位置或同名推断。

拒绝未声明/重复/缺少的物理 field ID、类型/nullable 不符、未知私有字段或版本、删除文件、schema 演进、嵌套类型、隐式转换、Iceberg/Delta/Lance 和源 writer。本片不宣称兼容 legacy manifest 的不同结构。数据集所有逻辑 ID 必须唯一；重复、NULL ID、过长 key_v1、假版本、坏对象和损坏 Parquet 必须失败。空固定源是否可用需正例认证，未认证前仍待支持。

拟议确定性分页为 logical_id_asc，每批至多 64 行且canonical ReadBatch完整envelope至多768KiB，完整 schema 不投影；ordinal 只标识页面。重复同页必须保持逻辑记录/版本/顺序，实际重复 I/O 和输出仍计费。越过终页、篡改 binding、撤权、到期、取消或超限失败，不返回伪 complete/truncated 成功。物理文件/row group/row offset 在内部逐行保留，不能从排序后 ordinal 反推；B-L 公共接口仍待单独冻结。

## 权限、预算和成本

只读取已获当前授权并受保护的固定对象；pin 不是授权证明，每次读取和输出均重新验证。缓存若存在也重新授权，不能延长期限或复用另一 query 的预算。与 P03 使用同一查询的真实累计计量：包括重试、失败和缓存命中；不得从返回字节或文件数量推导远程请求数。

规划硬范围：metadata 至多 64KiB；至多 32 个 source 字段、4 个数据文件、总 16 个 row group、1000 行；单数据文件至多 1MiB、累计数据输入至多 4MiB（metadata 另计且两者均消耗原 query 字节预算）；解码工作集上限 8MiB。实际 context 的更小请求/字节/内存/输出/期限约束优先。先预留输入、解码值/容器、行、排序及编码输出同时存活的保守空间。首片拟采用下述受限纯Python解码，不调用原生Parquet/Arrow解码；其它编码在分配前拒绝。逻辑预留与进程RSS分别验收，不能把后置nbytes当作硬限。

组件测量冻结为每个完整小型读取 cohort 至多 5 秒、单页至多 1 秒、进程峰值 RSS 至多 512MiB，同时服从原 query deadline。记录 metadata/data GET、应用与实际 wire 字节、校验字节、Arrow/逻辑内存、RSS、分页和清理；明确应用缓存与 OS 缓存。首次组件测量见文末精确报告；OS缓存未控，不建立冷环境、生产规模或提速 baseline。

## 兼容与恢复

新 reader/私有 metadata codec 与旧 alpha 并列验证，不迁移或写源、发布目录、回收对象、训练数据。出现校验/授权/取消错误停止输出，释放自己拥有的解码资源；查询 pin 仍由目录 owner/可信 cleanup 精确释放。保留失败 trace/输入摘要，在新目录从任务 checkpoint 恢复代码；源、对象和 PG 外部状态须独立对账，不以代码恢复撤销它们。

完整场景和未解决的实现风险见[计划](../design/fixed-sources-change-plan.md)、[场景表](../design/fixed-sources-scenarios.md)。当前通过层次仅为文末列出的本机组件，完整任务、主线与I1证据仍待验收。

## 实施前冻结的格式和计量合同

以下实施记录保留合同与逐轮修订的先后关系；其中当时的“待实现/未运行/missing”由文末本轮实测状态限定更新。

首片只准入标准Parquet的flat required/optional列、UNCOMPRESSED、DataPageV1、PLAIN的UTF8 BYTE_ARRAY/INT64/BOOLEAN及单层nullable定义位RLE/bit-pack；必须有明确physical field_id。生产路径不导入PyArrow或其它native Parquet解码器。压缩、字典、DataPageV2、重复/嵌套、加密、外部column chunk、page index和其它逻辑类型均明确unsupported；不是一般Parquet兼容性声明。PyArrow仅作为独立fixture writer/reader验证互操作。是否准入仍须源码独立复核及真实测试。

Compact Thrift/footer/page parser在读取长度、列表元素数、深度、行数、字段数和UTF8字节数后才分配；只按已经收到的有限bytes解析，不按不可信长度扩展、解压或预分配。每小步检查同一取消/monotonic截止，所有坏长度、溢出、overlap、重复字段、未知语义和未消费数据失败。普通text至多4096字符；逻辑ID/版本严格遵循A字符集与128长度，不截断或隐式转型。允许物理列重排：metadata source_schema数组按source_field_id严格升序canonical摘要，实际完整物理schema按ID核对name/type/nullable，不按位置/同名推断。

同一可信P03对象reader的scope与ObjectReadPort成对注入，不能创建新账或用文件数推请求数。P03内部object bytes输出和最终ReadBatch均保守收费，原scope已保留输入内存继续计入；source额外值/行/编码预留不得覆盖或清零它。source自身非阻塞串行锁不得包裹P03 scope.operation非重入锁。每batch Usage请求/body/output/elapsed为本调用counter delta，memory为本调用期间受保护的实际逻辑占用峰值（包含此前仍活跃保留），不取历史峰值差；同页重放记录不变，费用随实际工作重新计。query硬限以父scope累计账为准。

分页先完整验证至多1000行/16groups、全部唯一ID及排序前物理位置，再按完整Resource schema、logical_id_asc、64行和768KiB编码上限确定页边界。边界由固定记录canonical bytes确定，不随usage数值变化；计量字段留固定保守空间，单行不能容入时整次resource_limit，不返回前页部分成功。空源只允许files=[]且metadata仍属于revision，经正例后才可支持；revision.objects完整ObjectRef集合必须恰等metadata+files；去重且metadata不得作为data，额外或未列对象拒绝，empty时仅metadata。此规则比A更窄且不认证有其它对象的revision。所有能力仍missing。

计量接线拟采用connectors私有SourceScope继承现有P03 ReadScope，由可信组合根一开始建立唯一实例，再交给同一个FixedObjects与source reader；不得在source内部为已有query另建scope。只扩展batch串行、局部memory观测和更小page/cohort检查，复用父query计数/保留/授权/取消/原wall及mono期限。cohort锚在首次read_batch设一次；batch期间其它thread直接操作同对象port拒绝，避免混账；page开始已活跃memory计入局部峰值，零新reserve时也不为0。scope、对象port与binding实例关系必须校验，首扫包括所有I/O/验证/排序与清理计时，不搬到构造函数。

实现独审发现的结果构造边界也纳入本轮合同：Usage.elapsed_ms取完整首轮封套构造/校验和重新授权之后的最后观察点本批delta，随后仍正常构造并校验最终不可变封套。它不冒称包含最后序列化/校验/返回清理的数学精确时长。实物driver必须独立记录整个read_batch调用的真实page_elapsed、最后观察点/返回点及finalization_tail_ms，原1秒单页、5秒cohort、query wall/mono deadline与取消覆盖整个过程，不以Usage快照替代总耗时验收或隐藏尾段。所有请求/body/output实际费用仍按父账delta，最终封套实际len在返回前扣账。失败清除reader持有的decoded记录/位置/页面缓存，禁止同reader继续；P03输入、已收费预算和pin不回滚，仍由原query owner结束/精确清理。

同一reader调用按非阻塞所有权串行。未取得该所有权的并发请求只拒绝，不清除或poison在途owner的缓存；取得所有权后发生准入/解码/输出错误才清自身缓存并要求fresh scope。所有可能拒绝的构造/授权/取消/期限检查和计量准备均在最终delivered提交前；delivered本身作最后检查并按实际封套长度记费，随后只返回已验证引用并退出固定资源上下文。reader内记录precommit观察点；外层driver再记录真实返回点/总时长/尾段，不能把提交前时间叫作调用已返回。

当前实现进度：6个生产候选与20项unit设计经R3独立源码审查，新增真实S3/TCP driver仍待独审和执行；没有运行通过证据。实际Lab配置/原始服务日志保留在artifacts/private/，公开run只留许可合成源、绑定、数字trace与摘要。

源码独审后的补充准入合同：合法DataPageV2明确unsupported_capability，缺失/损坏V1结构仍corrupt_object，不改变白名单。验收任何失败仍保存主错误、身份复查错误、实际owned/removed/日志返回码和当前scope/response数字摘要；身份复查失败不能抹去主因。取消在数据第二个GET确实到达后才触发，记录请求计数/触发和返回时刻，不用准入前取消冒充在途取消。全部新增断言仍待实测。

当前候选含27项unit设计（reader13、codec9、driver证据5），新增wire V2分类与失败/取消证据修订均仅AST检查；尚未运行，不能依据候选代码标支持。

第二轮driver源审7777b208的先行修订：普通unit包入口也必须可导入driver，不依赖coverage脚本偶然附加的harnesslib路径；真实backend每个新query的实际刷新binding须在第一次read前保存canonical bytes/SHA/query_id及许可输入索引。每次已返回page/replay的wire与完整调用计时在验证断言前后均有独立journal，失败finally也保存已完成部分；upload时的旧fixture binding不能冒充当前query输入。补证据负例必须证明成本断言失败仍能关联实际binding与已返回page，不将unit mock当作S3或deadline通过。修订前当前20file/27unit仍未执行。

本轮修订后候选为28项unit（reader13/codec9/evidence6），新增成本断言失败仍保留实际binding/已返回page的负例设计。每query第一次read前落实际canonical binding和独立输入索引，每次read/replay在finally落wire+调用journal，case结束再归总；代码仅AST，28项仍未运行。


### 首次互操作修复候选：可选列大小统计

首轮普通unit尚未通过：PyArrow22的受限V1文件即使关闭普通统计仍写入列元数据`SizeStatistics`，此前候选把它当未知字段拒绝。待修复白名单只增加该可选结构：严格核wire类型、非负且有界的字节数、平面repetition/definition histogram形状及总数；允许已观测writer的空histogram表示省略。实际解码后仍核文本UTF8字节总量与NULL数量，不用统计跳数据、改变身份或推导预算。未知统计字段、重复/嵌套层级、矛盾计数继续拒绝；原压缩/字典/V2等拒绝集及所有预算不变。此段是修复先行合同，尚无通过证据。


V1页头还允许已观测PyArrow22写出的可选**空**`Statistics`结构；空结构不提供剪枝/NULL推断依据。非空页统计及其它未知页字段仍明确unsupported，错误wire类型仍corrupt。此兼容修复尚待复验，不改变DataPageV2拒绝或输入/输出预算。


## 本轮本机组件实测与限制（2026-10-21）

同checkout已提交P03对象reader与P04六生产模块完成首次互操作；20文件冻结SHA `ec182c227ca6a63bd6389b961c3813358d83fb4c46d60ebac6cd93f6af0f9b31`，完整树摘要 `fd1b4947` 起始的实际身份保存在三报告before/after。后续文档与shared门禁接线不复用它作为当前全树验收。原32项与新增6项边界unit通过；随后完整Python重验270项测试全部通过，51个生产文件4474/4474行、零缺口/零排除，源码前后身份一致。实际python.json SHA `4a851aca3bf769fa5483eb989419dde227dd43c6a5e72fc067ea10b6378c4038` 位于artifacts/p04-python-coverage-boundaries；Rust严格覆盖和完整任务门禁仍待重验。

实际 `artifacts/p04-component-first/fixed-sources-{functional,performance,fault}/report.json` 分别SHA `d447f587f760e0605e1c838bcd85a20346b3e04b75d30af0c0ea9f4a83b5e22b`、`407ef10ead72769ca7cb992e900a5f6d713fce976978e217dce5fd81ebeae3b2`、`71472ecf1429e09d229064ec9ddcfd200658084e94f7d8e27f3e5d4adb9b6062`，通过6功能样本、4性能样本与23故障case。固定11事实、130行两文件64/64/2三页、空源、类型化key与派生revision均核独立真值；真实S3覆盖写后仍按旧精确VersionId读，冷2/3 GET、暖0。全部样本最大page41.765ms/cohort63.335ms/逻辑预留1,903,748B/RSS102,612,992B均在原预算内，属于该小负载观测。

独立审查逐267份安全原始文件、28返回wire和实际账本复核；实际第二数据GET后取消全调用10.896ms、触发到返回2.849ms，故障结束listener=false、threads=0、active=0。200ms父期限用例因已有cleanup余量在0 GET前拒绝，仅证明更短父限优先；没有证明一次真实网络等到200ms到期。监听器清理有最终状态，尚无单独teardown总耗时度量。

性能使用公开256KiB应用缓存，OS缓存未控制；fault坏源的sealed-v1不是实际S3版本。授权仍是本机有界内存callback，不是PG。未留独立HTTP签名/response原头/完整capture回放，不能把安全证据复核写成全面秘密扫描。一般Parquet、真实云、P10/P13、I1及生产规模仍未验收。正式当前checkout完整门禁、正常hook/commit后复验、上游PR12与本片PR/精确main/双CI均待完成。


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


## 受控 producer 与 Rust 真实 IPC（规划，待实现及验证）

本片目标是固定 PG 真实发行身份→P04 真对象读取→逐页真实 IPC→Rust 唯一 SQL 执行；尚未提供可运行的新用户入口。后续显式组合入口必须先固定 derivative Linux runtime、真实镜像身份与同 Linux 单调时钟；不能将 host Python 和容器 Rust 时钟直接拼接。首次输入沿用完整11事实及双源130行64/64/2，不使用模拟 Source 代替真实链。

查询在 bind 前取得原始 T0、取消与总截止。先唯一 SQL claim/prepare，实际授权完成后，才预授 producer/resident 与 receiver/decode 信用并 OPEN。OPEN 从真实生产计划报告可信 total_rows/page_count，数据仍经既有白名单校验，不返回内部 state 或整 rows 指针。发送 DATA 前 receiver 必须已持许可并直接填其预授缓冲；不足明确 resource_limit，不先收完整 payload 再申请。普通 A 字节及签名语义不改；located 在新 IPC profile 暂拒绝，现有直接路径不变。

新真实 PG BindRequest 事前申请已批准 P05 trial 全 query managed256MiB/output32MiB；producer 是同父一次收费的≤8MiB子cap，不另开账本重复扣费。所有 binding/host/page/cohort 截止及预算继续逐项 min。该组合合同不是产品默认或原 C3 同预算性能。保留 P04 原2源、64KiB metadata、4文件/4MiB、16RG/1000行、总32物理字段、64行/768KiB A、1s/page和5s/cohort；新 IPC 联合 profile 若受 Rust32页限制，超32真实页明确拒绝，不截断。768KiB A 仍需实际 credit 可承受，不能自动加预算。

不可变 A 的 page-prefix 与实际执行累计分账：open费用独立，后续 finalization/delivered/传输 tail 不回写 A；逻辑 A output 与 IPC 控制/物理重传另栏。OPEN/READ 期间只作 local checkpoint，不递归向同一阻塞 worker 发 AUTH；完整 PG ticket settle 后再真实授权与 fresh 时钟。所有未知费用保留已知下界，native/server 费用仍缺失。

一 query 一个 owned worker。close 只归还自己 mint 且对象引用销毁的 logical leases，不手减旧 Scope.memory_current；Rust 持有的 raw/Contract/Arrow/result 仍各自计费。成功要求正常 worker exit+wait/reap、完整费用确认及 exact pin release；超时按启动代际精确 TERM/KILL/wait/reap，丢响应先同 seq 对账，不重复 bind/read。bind unknown 仅原完整 request close，absence 仍 cleanup_unconfirmed；杀进程不证明远端 PG 停止。兼容与恢复保持原直接 P04/C3 路径及失败原件，验证缺失时本节持续标待实现。


### 受控 producer slice1 本地普通验证（2026-10-23）

新任务9558d0ea的本地生命周期/同点witness/子信用切片完成首轮普通验证：新producer16/16与原7leaf direct source79/79通过，结果`artifacts/p04-controlled-producer/slice1/ordinary-first/result.json` SHA256 `52cb9ae48af7a74031616165ec3fa93c062fdda2de96078b7e11ec1d12ba897a`，分别实际进程2.816s/1.429s。48相关路径前后SHA一致，绑定源码修复清单`5fe26bc5`；ROOT独立核95项逐test、日志和进程终态，审查SHA `02ee3c3635cd2bd82c817371aa1c37f0622bf80464076d4fdda5a416a4a23b66`。本结果文字在测试后追加，不冒充已跑源码身份。

验证使用真实PyArrow写出的有界Parquet fixture与mock对象transport，覆盖实际load后11/130 rows/pages、64/64/2、open成本不再写入首page A、精确usage_point/at_a/tail、单父子lease与ACK/close时consumer输出仍live；新增并发release确定性barrier及safe generation边界也通过。它只证明本地实现及原direct回归，不证明PG发行、跨进程Rust权威、实际IPC/receiver预授、worker kill/wait/reap或真实完整链。第一SOURCE审发现release竞态/generation无上界并保留，窄修后SOURCE增审通过；没有通过加预算/删原测试消除失败。

该片仍未完成socket adapter、Linux PG/S3 namespace与实际query binary对接；实际PG→P04→Rust全11/130、新组合256MiB/32MiB真实binding、性能/故障与全原base门禁、正常hook/commit/post、task-finish/checkpoint、依赖PR18/双版本CI/main仍missing。close仅本地logical状态，旧Scope保守账未手减，native/server费用缺口保留；上节规划中这些行为仍待实现与验证。


### Linux 原始 anchor 导入切片（待实现、待独立 SOURCE 审与容器验证）

可信父进程先预付 bootstrap，再从固定继承配置上下文导入 exact80B GLNA v2/clock1/unit2；本片只提供 storage typed 一次消费入口，不实现 FD/worker/BIND arena。Python 新建 ReadParent 保留 Rust 原始 u64 T0_ns、boot/session/nonce/代际，fresh Linux CLOCK_MONOTONIC 与 boot 验证；不修改既有 parent.started、不注入伪 clock、不声称两个进程共享 ledger。ns 时间域不套 safeint 计数上限，query 截止只取 min，C1 秒投影向下不延长。

每个本地执行操作携原始 operation/PG seq 与绝对 ns 截止，effective deadline 为 query/operation/page/cohort 最小值；原250ms准入及200ms清理余量同样约束更短 operation，退出操作不延长 query。错误/取消/重复消费/错 boot 或身份/未来 T0/过期/时钟回退明确拒绝，原 memory/直接读取路径保留。Rust 是唯一信用权威，Python 仅预授子分配与本地观察；native/server/完整 IPC 费用仍未知。

验证映射：新 test_fixed_linux_anchor 结构/边界/一次消费/min/slack/浮点舍入负例及原 producer16+direct79 回归须在独立 SOURCE 审后经固定本地容器执行；实际同 Linux boot 跨进程时钟、真实 PG→P04→Rust full11/130、完整 harness/PR/CI 另片，当前均未认证。先行计划与 before 指纹见 artifacts/p04-controlled-producer/storage-linux-anchor-plan 和 storage-linux-anchor-implementation。


### Linux anchor 本地容器 ordinary 结果（2026-10-23）

本片实际源码先经 ROOT 独立 SOURCE 审（0196214a），随后固定本地 dev image `sha256:b12433266fb4c63839b077165bee7c770ab8c0d3321d42b817b35232eb020350`、network none、rootfs/工作树只读、临时 /tmp 首轮执行全部115单元：新anchor13、原producer16、原direct79、原parent完整7，115逐项ok，unittest1.648秒、Docker attach2.078秒、容器退出0。106相关源码/测试/锁/文档前后指纹相同；本轮nonce与exactCID、终态、8个Docker客户端PID/PGID及精确删除回读保存在 `artifacts/p04-controlled-producer/storage-linux-anchor-implementation/ordinary-first`，result SHA `4a3ccfb5fda92a82bca55489ca1863a5a0c2eaf82e50337c2903bdd04faec301`，无HOLD。

这些结果只认证typed token结构、原T0/截止/slack/一次消费等本地合同和普通回归；其中Linux真实测试只在Python自身读boot/clock并导入，不证明Rust跨进程anchor来源。实际FD/bootstrap/BIND arena/PG→P04→Rust full11/130、query ABI与完整原基点门禁/正常提交/PR/CI仍待后续，native/driver/server费用未知边界不变。上方pending为测试前先行合同，此处只追加本次已执行范围，原C3与slice1历史证据分别保留。


### 私有 FD 实际接线开发（NOT_CERTIFIED，待实现与独立审查）

本次仅实现实验性 Python worker/protocol Source 接缝：可信继承三 FD、GFD2、80B GLNA v2 原始 Linux ns/T0、同一 ControlledReads/ReadParent/FixedProducer；它不是可用产品入口或验收通过。仅可信 composition root 可提供实际 PG C1、固定 backend 与事先由 Rust 原Owner预授的信用；缺 launcher/config/新target 时明确拒绝，不用模拟 authority 替代。完整原11/130与新6字段/2新metadata、固定256MiB/32MiB、producer8MiB、原1000/64/1s/5s及115回归仍为后续实证义务。

DATA 前必须接收许可/预约，短包、超额、hash/序号/身份冲突拒绝并停止输出；已发/未确认费用保留未知。ACK只销毁 producer cache/payload 引用，不释放消费者输出或整个Root grant。DF与结果编码后 CLOSE_PREPARE 仅停源、保留C1/pin与8MiB/W；最后同C1 AUTH_RETIRE 后退出，由Rust exact wait/reap及独立pin cleanup确认后才可释放父预约并fresh检查取消/原截止交付。最后AUTH之后不声称再观察远端撤权。旧本地close语义保持；当前无FD/PG/S3/native测试或兼容认证，完整原base门禁/PR/CI不可豁免。


#### FD 首片独审待修（未运行）

首冻结1aa0ec69保留。独审发现ACK函数局部A引用须在输出lease退款前销毁，以及CALL/PERMIT信用需严格safeint上界。仅窄修这两项与新负例；raw ns仍u64，原115定义/预算/launcher域保持。revision2 SOURCE独审后方可由ROOT安排普通运行，当前不标通过。


### 私有fd0入口与新target装配（待实现，NOT_CERTIFIED）

本片拟实现PCF2固定配置/原80B Linux anchor一次导入、同C1实际PG与FixedBackend、实测runtime HELLO；同类fixture-only SHA allowlist不是真实I1认证。新SQL target只改逻辑schema/映射与新SourceVersions/两metadata，保本轮原两Parquet raw/ref和全部11/130 cells；不重写旧dataset/metadata、不造binding。现revision2/实际142保留，新增接线与负例待独立Source审和ROOT实际运行。原预算/完整门禁/PR/CI不减，W/native/256和完整FD链仍未认证。
