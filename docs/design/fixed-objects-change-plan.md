# P03 固定对象读取首片变更计划

状态：**恢复树原始范围完整INITIAL通过，最终提交与交付待完成**。以下为原任务起点，恢复任务与最新证据见后文。基点 `4d6baca888421d90f146679ef71b0e555fe60881`；分支 `codex/p03-fixed-objects`；worktree `/Users/chad/dev/guradb-p03-fixed-objects`；起始树干净。task `653a8ca54b7845ccb03ecf777afbaf36`，label `p03-fixed-objects`；恢复 checkpoint `checkpoints/20261021T015433Z-before-p03-fixed-objects-dd387582`。

## 目标、归属与非目标

按 CF1-A/1.0 实现 storage 的固定 S3 版本全对象/可信整块读取、验证缓存、跨 attempt 的累计预算、整体 deadline 与取消。实际本机模拟后端和故障 server 提供新 signer/raw HTTP 路径证据。产品用户合同见[固定对象](../user/fixed-objects.md)，成功/拒绝/故障映射见[场景表](fixed-objects-scenarios.md)。

依据 ADR0004/0007/0016/0020、modules/storage/AGENTS、INV-002/006/008/010/011。源身份与版本、块证明不授信、缓存重新授权、累计远程成本和无后台遗留工作不能削弱。目录发布/GC/源 writer、真实 PG/P04/I1、SQL/HTTP、TLS/真实云/多机、STS 刷新不在首片。

| 独占文件域 | 职责 |
| --- | --- |
| modules/storage/fixed_objects.py | 实现 common ObjectReadPort，绑定成员/range、授权、缓存、校验与 transport 编排 |
| modules/storage/fixed_scope.py | 一查询一次累计 scope、monotonic deadline、取消、attempt/body/output/memory/trace |
| modules/storage/fixed_signing.py | 可信 loopback 配置、私有内存凭据、锁定正规 S3SigV4Auth 签名 |
| modules/storage/fixed_http.py / fixed_transport.py | 严格有限 HTTP framing、非阻塞 socket、整体时限与确定清理 |
| modules/storage/fixed_proofs.py / fixed_cache.py | 可信完整块表绑定与有界不可变 LRU；无目录业务权威 |
| tests/unit/test_fixed_objects*.py、tests/storage_support/ | 独立字节/绑定/proof 真值、测试故障 server/测量支持；不复制生产校验生成期望 |
| scripts/fixed_objects_acceptance.py | 真实 Seaweed/故障/成本 driver，独有 run 报告；每源不超 600 行 |
| docs/user/fixed-objects.md、docs/design/fixed-objects-{change-plan,scenarios}.md | 先行用户合同、实施和验证追溯 |

storage 只依赖 common 和本模块；botocore 静态 import 由 root 登记 external。root 独占 user README、harness/policy/architecture 等共享接线；交接时暂停本树写入。禁止修改 common、旧 storage、locks、根计划/README、覆盖率排除或阈值。当前 SDK client 注入草案已退役，不同时维护第二网络实现。

2026-10-21串行交权：p01_oracles明确冻结整树后，root独占写用户导航/本进度追踪、architecture的botocore external、policy三条真实driver与Python语法入口、harness风险选择及其防漏选测试。root先保存本轮文档diff，再修改门禁接线；作者随后只读独立审查精确diff。接线保留原命令、预算、覆盖率分母与planned全库门禁，不新增依赖版本或GitHub配置。driver或tests/storage_support单独变更也必须选择真实组件验收，不能只凭此次生产改动偶然带上门禁。

## 文档先行与切片

本计划/用户合同/场景表先于任何新生产代码。三文件新增 diff 已保存为 `artifacts/p03/docs-first.patch`，SHA-256 `7ad5f7dcc4bc0f152c782ccc61dbe59fa343a7bf77d71cfbc9cdfad7e4df854d`；不以计划命令输出冒充执行结果。

步骤：独立 worktree/venv/task → 三份先行合同及 plan → 独立 fixture/负例 → scope/proof/cache/签名与有限 transport → 编排与单元边界 → root 接线/独立源码复核 → 获独占资源窗后真实功能/故障/成本及完整 harness → commit hook → 原始 base post-commit check → task-finish/PR/CI/串行集成。

局部 unit 运行也须先向 root 核对资源窗口；不得自行 cargo、全量 coverage、完整 harness、真实容器或性能 driver。初次按拟议九路径的 plan 实际选择 contracts/functional/harness-tests/performance-smoke/policy/python/repository/stability-component/unit-coverage；storage 反向 DAG 影响 catalog/cluster/connectors/gateway/index/query/storage，选择 INV-001–012。unit-coverage 包含全部 Rust 覆盖义务；不能因为未单列 rust suite 就免除。最终范围还须再次 plan，缺失不转绿。

## 不变量与有限 transport

ObjectRef 逐值属于 binding 的 metadata/objects/index shard 集合，成员校验后从已授权 canonical bytes 取私有快照，之后不跨await读取caller字典。所有请求携带指定非 null VersionId。whole 模式仅全对象；block 模式验证可信 authority 逐值登记的完整身份/size/whole SHA/块表/宽度，范围完整覆盖块。每次输出重查当前 epoch，pin 不替代授权。

首轮 root 独立逐字审查与作者自审共同确认 ref TOCTOU 为P1：旧候选可能在callback/传输中消费变更后的摘要并污染原cache key。本批最小修复还包括精确endpoint字符串、仅单明确backend且key匹配、bucket=m0-data/region=us-east-1/cache≤256KiB、取消callback异常失败关闭。凭据规则先行收紧为每次read含cachehit都要求声明expiry覆盖原deadline；补暖缓存过期/短expiry拒绝。该轮是独立源码复核，不是GitHub Approval；修后须新指纹/局部复验/复核，旧18项证据不外推。

可信配置只接 http://127.0.0.1:port、path-style、认证 versioning bucket；原始非阻塞 socket、GET、唯一 Content-Length、Connection:close 与 EOF。拒绝 DNS/IPv6/TLS/非 loopback/真实云/代理/重定向/TE/chunked/压缩/HTTP2/1xx/无长度/连接复用。用正规 S3SigV4Auth/AWSRequest 签名与终态序列化，key/query 只编码一次；不自行实现密码学，不透出 SDK/socket 对象。

scope 原始 monotonic 上界覆盖连接/发送/首部/body/EOF、失败与重试；wall clock 后退不延长。独立取消 callback 取消所属 coroutine，finally 关闭 owned socket并清理 handle/future，不开线程/executor、不访问 DNS。持续就绪读显式让出 loop并检查时限。已有 running loop 的同步调用在 I/O 前拒绝；首片同 scope 串行，不伪称全局调度已完成。

首部逐字节读，避免 body 被未计量预读；body recv_into 每个实际 n 都累计。保守 attempt charge 与实际 GET 分列；内核未 recv 的字节不冒充精确应用计量。输出转换双份与 cache/proof/存活返回字节均预留，SHA 分块处理且记校验字节。日志配置归组合根，不在库中改全局 logger；真实捕获证明 session token/签名/URL 密钥不落盘。

## 预冻结真值与预算

| 项目 | 验收合同 |
| --- | --- |
| 固定输入 | 16B 手核对象与 2MiB+17B 确定性对象，固定生成规则/seed、独立 whole/block SHA 和输入摘要；不提交大媒体 |
| 缓存工作集 | 64KiB 常规块、17B 尾块、256KiB cache；相同访问序列分冷/热/超缓存，全部逐字节比较 |
| 有界资源 | 对象 ≤8MiB；请求 ≤16KiB；首部 ≤32KiB、行 ≤8KiB、64字段；64KiB body chunk；实际 context memory/bytes/requests/output 更小则拒绝，不漏计双份 |
| 请求 | 最多3 attempts，原 deadline/额度内；EOF 哨兵额外预留1B；连接失败也保守计 attempt；无隐藏 SDK 重试 |
| 时间目标 | I/O 比原 deadline 提早200ms停止，最小准入250ms；取消停止/清理目标100ms。均为未实测验收目标，不承诺硬实时，失败后依据证据复核而非抬值消除回归 |
| 成本证据 | GET/attempt、应用 header/body、proxy wire、校验字节、cache hit/eviction、逻辑memory峰值/总RSS、耗时与清理。无旧产品baseline，不声明QPS/p99或提速 |
| 成本候选上限 | 每独立 cohort ≤10000ms、验收进程RSS ≤512MiB；同大对象分别测fit冷/热与完整超缓存重复序列，不用fit输入替代完整工作集。尚无运行证据 |
| 故障 | 版本缺失/错版/错SHA/短读/多读/错framing/429/503、连接/首部/body停顿与滴流/有效body不EOF、撤权/取消/预算、日志泄露与恢复 |

已有单 bucket probe 只作为后端能力前置，不复用其通过结论作为新 transport 或 P03 认证。预冻结目标和输入未通过不得减少工作集/省校验/换暖缓存。

## 兼容、失败与结果

新入口独立，不改 legacy 行为或持久格式，不迁移生产数据。错误、取消与校验失败不得输出部分成功或 fallback latest。清缓存后可按同版本重取；Test Lab 写入/清理单独记录。失败保留日志/diff/输入配置和当前假设；同条件两次无新证据失败定位根因；需代码恢复使用上述 checkpoint 在新目录，不破坏当前现场。

当前：7生产模块、2个unit文件、独立fixture/故障server/计量proxy与真实driver候选已落盘。获 root 短窗口后运行18项unit：首轮4.225s虽断言通过，但有误伤asyncio内部socket的测试注入warning，保留 `artifacts/p03/unit-first-20261021T0230/`，不计干净通过；只对owned AF_INET注入后重验18项4.217s、wall4.35s，日志无warning，前后源码列表相同，证据 `artifacts/p03/unit-owned-socket-fix-20261021T0250/`。这仅验证当时本机Python3.14候选；后续driver/文档变更尚未运行。

上述18项历史阶段的真实Seaweed/driver/独立审查当时待完成，后续证据见下文；完整门禁、最终commit/checkpoint/归档、PR/main CI仍待完成。不得据此将P03整包或I1标完成。

2026-10-21首轮真实functional在35.272s以exit1结束，前后25文件SHA一致，已停止未跑performance/faults。原始失败、runner与Lab退出日志保留在 `artifacts/p03/real-functional-20261021T025057Z/`、`artifacts/p03/real-driver-logs-20261021T025057Z/`。ClientError发生在special-key fixture PUT；容器日志最后记录repeated-separator场景，但未保存后端错误码，不能判定是key语义还是其它后端拒绝。此前路径到达该点不算完整功能通过。

下一最小修复仅补验收诊断，无用户行为变化：fixture PUT附固定case_id/stage，failure.json仅白名单ASCII字母数字且长1–64的Error.Code与整数HTTP状态，拒绝字段用unknown/null；不记录SDK message、URL/key、header或凭据。用恶意Error字段canary的持久化负例验证脱敏。保留全部四个special-key输入、生产行为与预算，先审查新指纹，再单独新目录运行functional取得确切错误；不得预设支持/拒绝或自动碰绿重跑。

新诊断 `artifacts/p03/diagnostic-functional-20261021T025950Z/failure.json` 确认 dot-segment/fixture_put/SignatureDoesNotMatch/403，35.340s exit1；持久化脱敏新增unit通过。纠正此前依据最后PUT日志推断repeated-separator失败的假设：点段在PUT handler日志之前被拒绝。诊断源码manifest `4861080989a2ff73cd8c777c205f212d84b5c21819c942979d8c11aaa1b7021f` 及原403全部证据保留，不声称已定位SDK或后端内部归一化机制。

据该证据收敛待认证首片：实际 `.`/`..` key段在模块输出/缓存/I/O前与纯签名入口均unsupported_capability，不重写key；字面%2E不是点段，UTF8/%/+/重复斜线继续原成功验证。四个special-key场景仍全部保留：原dot PUT须明确得到同403，单列为后端拒绝而非GET认证；另构造negative-only ObjectRef证明0 GET/0输出，不冒称占位version为真实后端版本。新增 `.`, `..`, `a/./b`, `a/../b` 与暖缓存拒绝负例，不改变大对象/缓存序列/预算、A或完整P03目标。先保存本轮三文档diff，再修改行为并交独立复核，未跑项仍missing。

点段候选manifest `afbf32c32cf09f1f7f82f960354d75de994abd98e2e8dd0ad392b1e87560b9f7` 经root独立源码复核后，25unit+policy定向与三个真实driver均exit0；原始证据为 `artifacts/p03/dot-validated-{functional,performance,faults}-20261021T030629Z/` 和同时间runner目录。真实固定旧版/Range、三个成功特殊key、dot PUT403与模块0GET、冷热/超缓存、deadline/取消/日志候选通过，但仅绑定该旧SHA，不替代后续计量修订与完整门禁。

本轮仅补可观察性：正接收时记录常量大小的最后header/body接收时间，不为每recv扩trace；统一验收快照持久化原bound_at/deadline/remainingTTL、本地started与只减少的deadline锚、应用header/body/wire/verified、memory_current/peak、trace_dropped、socket关闭及调用方观察返回时间。固定case记录认证/撤权/缺版本等拒绝scope，快照不包含描述符/URL/header/异常/凭据。应用received与proxy/server sent明确区分，内核未recv差异不强行相等；scope自身wire==header+body，成功原字节真值及proxy body等式保留。算法、预算、四key和成本序列不变，补真实socket计量和快照脱敏负例；新SHA须独立复核、完整重跑后才可更新支持状态。

trace原上限128在完整33块scope可能截断，因此另加一个常量大小last_socket_close_elapsed_us，由既有socket_closed事件更新且不受trace截断影响；不从保留trace末项冒充真实最后关闭时间，不扩大trace或隐去trace_dropped。

## 最新局部结果与仍待完成的交付

root独立通读上述各轮精确diff及负例，实际重算最新25文件manifest、三个真实report SHA、全部12/4/12 scope的wire/TTL等式、mono截止上锚与lastclose≤return、日志审计和Python覆盖率，确认本轮局部证据。此为作者外的独立源码/证据复核，不冒充GitHub Approval。生产/测试/driver冻结manifest `7fd121054724d2697997b9b88958e6204a9ed616bdf14254d5d441063237b97c`、checkout `8e8732a4ad19c248d1a8ace53a97fecdc713f5757285da4bf1aa7c47d487f857`；本次仅更新三文档，新文档SHA不沿用旧报告通过。

| 命令/结果 | 本次原始路径（均为该worktree下） |
| --- | --- |
| `python -m unittest discover -s tests/unit -p 'test_fixed_objects*.py'`：26/26，4.774s；policy防漏选target 1/1，0.047s；均exit0 | `artifacts/p03/telemetry-run-logs-20261021T031639Z/`，含完整argv/stdout/stderr/exit/wall/前后25SHA |
| `scripts/unit_coverage.py --language python`：230 tests，3804/3804行，missing0/excluded0，exit0；保留PyIceberg解码器回退warning | `artifacts/p03/telemetry-python-20261021T031639Z/` 的result/identity/python.json；完整命令日志在上述runner目录 |
| `scripts/fixed_objects_acceptance.py --suite functional`：12scope，exit0，wall35.290560s；报告SHA `a04b5b0150563de611d9df9cfabb8e1c84a1beb40401a4a2297c13f0d0c6c174` | `artifacts/p03/telemetry-functional-20261021T031639Z/` 的result/input-manifest及Lab公开trace |
| 同driver `--suite performance`：4scope，exit0，wall23.880026s；报告SHA `c63f8a7b208a15b026ebd226eaf27c395710fdb19122ee524effee9bf510ac29` | `artifacts/p03/telemetry-performance-20261021T031639Z/` 的result/input-manifest及Lab公开trace |
| 同driver `--suite faults`：12scope，exit0，wall3.512903s；报告SHA `aa1c8b2ab9807f772d547e6be3f8fccf2c9b1198cb3849e245b9f57d8cb09f60` | `artifacts/p03/telemetry-faults-20261021T031639Z/` 的result/input-manifest；每个故障server注入/清理计数及scope trace在result内 |

全部使用worktree `.venv/bin/python`；Python3.14.7/macOS27.0.1-arm64，固定Seaweed3.97镜像 `sha256:bb05d66d2963b1cc48073190781c3dd29e2c4c88a2ae2986bf58e38c86d89c6e`。输入manifest canonical payload摘要 `58153548d6c708a0b6cd8b58bcb0832783462ede81bd267caf0038909d8a5bb2`（report.input_sha256；包装文件input-manifest.json的字节SHA为 `4e8f6841fb5cb525e64959c6ebaf72654f89d9c79ed9a32af98bde764fe52ae8`），16B与2097169B对象/64KiB块/17B尾块/256KiB缓存均未缩小。三driver均经实际组合根root DEBUG/token/secret/签名/URL canary审计，真实STS仍false。

冷fit/暖fit/完整超缓存/重复完整实际GET为3/0/30/33，耗时28.52/1.88/179.61/171.12ms，最高进程RSS101711872B，均满足原成本上限；完整两个scope校验/输出均2097169B。scope应用received header/body/wire与proxy sent分别保存，正例proxy body等式成立；失败滴流server多发送而应用未recv的1B明确保留差异。trace截断88/103项时，独立最后close仍真实记录且早于观察返回。五deadline场景含server idle502.29–506.35ms<700ms，取消含清理6.99–15.63ms<100ms；非硬实时SLO、真实连接停顿/TLS/跨主机及PG网络授权不外推。

已验生产SHA：`fixed_cache.py` fa0fd3ff818d42dc59e85db12811bfc75f29b6f0a0e4e435c67e2bcba77676fd；`fixed_http.py` b7f0da09abececbafcdfb75d0e8a03c30828da909df015b006abf9bc92837ec2；`fixed_objects.py` 63ac417fcad07f4ae3d59ae817267b747d8abc81832764183b488ae7015884ae；`fixed_proofs.py` dd69e4d5c9eb14dea2fee6d4844f15ef0f98b69f709d6ee576798f06efe13d0f；`fixed_scope.py` 11bbe8d661d7a366ba6eb19b8993f622b3f6df0efd6ea98a635b02dfa24ff2fc；`fixed_signing.py` 57f2b9d8d3b0cebc0a1be4a1dcf89765a5de87b1b1202a14037027cc96ed9ac4；`fixed_transport.py` ae39c1e4ce088b2eb8c671d2f138e60119542f4256c77fd218a727807ed10698。完整25文件清单在上述manifest中；这些源码未因文档更新变化。

安全raw归档候选清单准备在 `artifacts/p03/raw-archive-candidates.json`，仅列实际result/input-manifest/公开trace/安全stdout/stderr及SHA；不整拷Lab，不纳入auth.json、s3.json、凭据配置、原container日志或内存log capture。初次warning和403失败原始现场继续本地保留。实际归档必须在最终commit的原始范围完整check通过后，以其新报告与匹配raw另行完成；本清单不是已经归档的证明。

截至上述历史局部证据阶段，包含全部Rust的unit-coverage、实际plan九项完整harness、hook提交、提交后原base检查、task-finish/checkpoint、PR和精确main CI均pending，尚无该候选Rust通过声明；恢复后首次整仓结果及当前待验状态见下。真实PG/P04与P10/P13授权期限/取消配对、SQL/HTTP、I1、非loopback/TLS、真实云/多机、STS仍missing。局部子片不关闭完整P03或G1–G5，也不作为产品baseline。


## 原始范围恢复与 CI 证据接线（本轮先行合同）

原 dirty worktree、25 文件冻结清单6a6307f5及全部原始失败/局部证据保留。由原 checkpoint 在新目录 `/Users/chad/dev/guradb-p03-fixed-objects-recovered` 恢复；branch `codex/p03-fixed-objects-recovery` 在 clean 原4d 上先建立 task `aa7ad841fd3a456ea99eb2e1ddcfd8ca`、checkpoint `checkpoints/20261021T044639Z-before-p03-fixed-objects-recovery-d6d1511a`，再 clean FF 合入17d66c66。receipt base仍原4d，不能缩成17d。19独占文件转移逐字/模式一致；6共享域在root整树独占期间合成，保持17d的900秒coverage watchdog及全部worker修复。原653a任务在root核验完整25义务传递后已task-abandon（指向NEW任务aa7ad841），原dirty/raw现场保留，不标完成；状态证据 `artifacts/p03-recovery/old-task-abandoned.json` SHA `54d5cef70fb9ef2a783a3d7958af7d4766d3a7e6b688e8d44f705b88803a2730`。

恢复当时PR10双版本测试合并树已通过并合入17d，其精确main本地/远端验证仍进行中；当时仅允许本片源码恢复准备。现root已核验PR10主线闭合：merge `17d66c66a067eebe73280ce8d3488fb4f7cdcfe9`，精确main五项门禁报告 `artifacts/harness/20261021T044402Z-982e5f80/report.json` SHA `6d0e4932cf0c34fc263caf526ad00c013ad640ca4ae28adccaeea3d91ffe45ec`、checkpoint `checkpoints/20261021T044927Z-pr10-main-verified-935740fd`；[PR run39544118302](https://github.com/yizhouxw/guradb/actions/runs/39544118302)与[main push39545360623](https://github.com/yizhouxw/guradb/actions/runs/39545360623)的Python3.11/3.14均SUCCESS。本地报告已另实际读取/重算，远端状态由root核验。原局部报告只属于旧树/旧source，不能作为新checkout的fullcheck。后续plan/check、hook、postcommit/task-finish始终覆盖原4d完整范围，重测实际Rust及所有选中门禁。

本轮仅内部验收/证据接线，不改变固定对象用户行为或生产格式。先记以下义务再修改共享源码：以17d为底合入原6共享P03增量；增加3项真实driver命令后，10ready/29commands上界15720秒，另保留原600秒安装上传，总16320秒=272分钟，普通job取275分钟，release360、各命令/组件/产品预算和strict100%/原21条豁免不变。若后来上游增加driver，按实际policy重新计算，不能沿用此275或降低负载；hosted360硬上限仍检查。

P03公开raw归档明确拒绝Lab auth.json/s3.json；原whole artifacts/harness上传会包含这两个本地fixture配置，因此workflow path改多行并只排除 `artifacts/harness/**/fixed-objects-*/lab/auth.json` 与对应s3.json，其余报告/输入/公开trace/安全日志照常always上传。两配置是本地测试身份材料，未发现外部凭据读取；本修订守住已有证据边界。按pinned upload-artifact实际语法复核，并在当前PR实际ZIP目录中核两个路径缺席、公开结果仍在。此证据验证完成前不声称远端排除已认证。保持matrix命名、固定action SHA、14天retention、planned release missing失败和900工程watchdog。


## 首次恢复树 INITIAL 失败与 CI 负例夹具修订（docs-first）

原27文件manifest `472440416d14158d24527d7816e709a8dfeda1a828710982e573373cc5a83ee1` 在独占窗口完整执行原4d范围，9suites/33paths/26commands，matching新venv，runner wall736.648578s/exit1。报告 `artifacts/harness/20261021T045845Z-cf7a435f/report.json` SHA `b76b292daccc8dfd52eee68973ec9d5f659f0a195a069acb143494394da10d26`、checkout `ed21b0856881bd9f8736ed3ad82ec9a7187524972bd23f70916fb739f8f52546`；source/receipt前后不变。该首FAIL报告不修改、不拼成通过。

contracts、functional、performance-smoke、policy、python、repository、stability-component及unit-coverage八套件分别PASS；harness-tests105项中1FAIL，原log SHA `2d5ff58141323890c26ba1dd0569e6b70f9bc78995dcfcf83590d902e079a24b`。实际Python232 tests/3804行、missing0/excluded0；Rust真实cold LLVM eligible3323/3323、原始3344/3323、原21条排除、missing0。三项新driver均实际重跑，报告SHA functional `228a38356a3538a4559aea9f489b951de7d2ed18b1eef8cdbf9701b65dd95b0f`、performance `6680c5466c21d3def437b7e634a35ed912f094f181556b13053ba3f92117622c`、faults `e7036fc25f449f4d0efa6adac032c4d416a040ba0d4baa349371b4fec468bf70`；这些局部结果只绑定原472440/ed21，不替代后续夹具修订后的新验收。

根因经root实际读失败确认：既有 `test_job_above_hosted_hard_limit_is_rejected` 将整预算expression写死成release367/change250；P03增加真实命令后change最低272分钟，验证先报15000<16320，未进入预期release超过360的hosted断言。作者与root前轮组合复核均漏核该夹具前提；不归因为生产或阈值失败。先记录此证据，再仅改该负例：取当前workflow job，用有界 `re.sub(...,count=1)` 只将release数字替为367，保留当前合法change预算，继续证明hosted上限拒绝。validator、正式275/360、900watchdog、strict/原豁免、生产、输入与成本/故障负例均不改，不新增镜像测试。

完整初检后、任何后续cargo前已保存793个实际LLVM profiles共476523000B，private manifest `artifacts/p03-recovery/first-initial-profiles-20261021T051153Z/manifest.json` SHA `e4d242fa7deac1223a78e7ca8d2c1ffb8d56b83a87a629ab645cabac0745c2a6`；不纳公开raw。原report/argv/26日志SHA/身份/28scope等式与strict复核在 `artifacts/p03-recovery/first-initial-evidence/review.json` SHA `b1121904a4984652ff354822498f594c2c90398a523ea76f072abeba475369b5`；49项安全raw候选清单SHA `5a7478c082500370315d522d578a3416975cbc45c1ff7f55defc9fe6593dd1b0`，未归档，旧run未复用。该修订当时为新28文件源码候选、待独立复核与新窗口；后续实际重验见下，本段首FAIL证据保持原样。实际Actions ZIP排除认证仍待后续PR。


## 恢复树第二次完整 INITIAL 真实结果（仅结果文档更新）

获root独占窗口后，先运行整个 `tests.harness.test_ci_workflow` 模块，实际5 tests/0.169s/exit0；source前后不变才运行 matching `.venv/bin/python scripts/harness.py check --scope change --base 4d6baca888421d90f146679ef71b0e555fe60881`，正常plan九套件/33路径/26命令全部PASS，runner wall684.389798s/exit0。报告 `artifacts/harness/20261021T053114Z-e7619721/report.json` SHA `0e4364576a90dc69331eca368367e25f42eed3590d3ba251572338c5f28f965b`，HEAD17d66c66、checkout `e8798305c8b4fd87d31296e8c42fe3b94386c1432c3ae2ec52a4e3c04af59998`，28文件manifest `64f1cd3aab20ce86212968193654bb3c4bb2a3e42a21dc372bb6afd9a922c765`。完整argv/退出/耗时/前后文件身份在 `artifacts/p03-recovery/reviewed-initial-20261021T053114Z-b3cbcc6c/`，receipt仍active且base原4d未变；没有跳过失败套件或复用首FAIL的输出。

Python完整232 tests/24.646s，3804/3804执行行、missing0/excluded0；Rust真实LLVM eligible3323/3323、raw3344/3323、原21行排除、missing0。coverage identity before/after相同并等于report checkout；9阶段起止完整，900秒工程watchdog/strict/分母未改。26条实际argv逐条等于当前policy展开，全部日志SHA复算一致。作者只读复核 `artifacts/p03-recovery/reviewed-initial-evidence/review.json` SHA `eec5665af944de09673ec47c30b9d51aa26a763923bc66d0e9678d7381760010`；root用matchingvenv独立validate_report/current28/argv日志/coverage身份/input摘要及首FAIL复核PASS，记录 `/Users/chad/dev/guradb/artifacts/reviews/p03-initial/review-envelope-initial.json` SHA `15013b0422712d812a6b61c6fe951d6f0215b2bd925316150a66add255b995eb`（后补三driver28scope独立等式核验的完整review.json为 `8ccce12422a9cb4ef5fd3a29f12e559c33a8db845c233931ff42195aa690a84e`），不是GitHub Approval。

| 本轮真实driver | 同一fresh harness目录内的raw与SHA |
| --- | --- |
| functional：12scope，固定旧版/范围、特殊键、拒绝/撤权/凭据通过 | `fixed-objects-functional/result.json` SHA `204a309141965940cd6943916acb9a744f13a130666aa4c5ef2953fada9830a4`；input-manifest与Lab公开trace同目录 |
| performance：4scope，固定成本序列通过 | `fixed-objects-performance/result.json` SHA `399f1f8a1d56d0df0756dec330debf4afe25db49c9ee08297c7519d1838c5f50`；input-manifest与Lab公开trace同目录 |
| faults：12scope，真实socket注入和清理通过 | `fixed-objects-faults/result.json` SHA `59b949c5572b129d89d8e617c6e548eebe1d10a9de44f250b4ba19342ee130e2`；input-manifest及每case trace/收发/清理计数 |

固定镜像/锁/环境与输入均重新绑定，canonical payload摘要仍 `58153548d6c708a0b6cd8b58bcb0832783462ede81bd267caf0038909d8a5bb2`，input wrapper文件字节SHA仍 `4e8f6841fb5cb525e64959c6ebaf72654f89d9c79ed9a32af98bde764fe52ae8`，两个摘要域不混称。16B/2097169B对象、64KiB块/17B短尾、256KiB cache与完整工作集未改。冷fit/暖fit/完整超缓存/重复完整实际GET3/0/30/33，latency29.40/1.65/178.25/155.49ms，最高RSS102039552B，原10000ms/512MiB上限保持；完整输出/校验均2097169B。五deadline注入含server清理502.55–507.95ms<700ms，取消含清理5.90–16.04ms<100ms；28scope的TTL/wire等式、monotonic上锚、lastclose≤观察返回及数字白名单均核验，应用received与server/proxy sent仍分列。每个组合根root DEBUG canary审计通过，真实STS false。

本轮结束且任何后续cargo前保全790个实际profiles、476500392B；private manifest `artifacts/p03-recovery/reviewed-initial-profiles-20261021T054309Z/manifest.json` SHA `dc71dc90e28f9a513e2f541ef035687b9cf6a9c096651247fc6c5fcd42436ea3`，tar SHA `3b4cb72379b6c713a9766da255463616ed084774737b877c8af8cf14e716b702`，逐成员字节及源前后校验完成；不纳公开raw。51项安全raw候选 `artifacts/p03-recovery/reviewed-initial-evidence/safe-raw-candidates.json` SHA `617d3e4d7d6806a4b07ee6bbd30dd235ea8146483ce010cca4003c0d36c1c7f7`，实际SHA/bytes与canary内容核查完成，未归档；排除Lab auth/s3配置、整Lab、原container日志、raw SDK capture、python.data/HTML、venv/target/profiles。旧b76b292首FAIL和793profiles原样保留，未把局部结果拼入新PASS。

现在仅更新本片三结果文档，其余25文件（生产/测试/共享接线）字节保持64f1cd冻结。上述PASS只属于修订前完整28输入；本次文档更新不是新checkout已通过声明。下一步仍为独立复核/正常hook、精确最终commit原4d完整postcheck、task-finish及匹配公开raw归档、PR双Python CI/实际artifact ZIP两私有配置排除核验、串行merge与精确main验证。无hook/stage/commit/task-finish/push/PR，runtime和profiles bulk I/O已释放。PG/P04/P10/P13、SQL/HTTP、I1、TLS/真实云/多机、STS与planned完整产品门禁继续missing；本机synthetic首片不升级成产品baseline。

## clean主线接续后的当前现场（本段为内部状态）

PR11私有Compiler提取已合入精确1e4f6a6c26eb28982f4b61cc75aa05e290211809；主线17d→1e4的新9suite/24命令本地检查bc049da2及checkpoint071032已通过，root独立实际834份raw三端核验72e21975；两版本main push39558459736仍运行，未判完整主线闭合。新目录source-only准备可先行，前一main未验收不合下一PR。

本片现恢复至/Users/chad/dev/guradb-p03-fixed-objects-main1，branch codex/p03-fixed-objects-main1；clean原4d先task-start55eb29fb62c645c48dc205760a089a2c、checkpoint checkpoints/20261021T070858Z-before-p03-fixed-objects-main1-6e4b4e37，再cleanFF1e4，原base仍完整4d。P05五上游路径与P03二十八路径无交集，28bytes/mode逐项等7ba8备份，index为空；恢复记录af21c21a及原argv/时序留本树artifacts/p03-main1-source-recovery/。旧aa7恢复树、653a原树dirty/raw/首次FAIL/成功INITIAL/profile全部保留；aa7尚active，只有全部承接复核后才abandon，不标完成。

root核对新receipt/28实物/5上游字节后，只追加本状态和进度说明，生产/测试/门禁接线保持原28冻结语义。新matchingvenv/full plan、正常hook、提交与原4d cleanHEAD freshpost、task-finish/显式raw归档/双PRCI/ZIP排除检查/主线验收仍待执行。正常hook将作为当前新checkout首次完整检查，不再另跑同输入INITIAL；旧9suite报告只保留其原HEAD/checkout含义，不挪给新树。所有产品/组件预算、strict100%、原21排除和900工程watchdog不改，实际plan选取及ready预算按当前policy重核。

## PR12 CI fixture诊断后续：新恢复任务与先行合同

在原checkpoint `checkpoints/20261021T070858Z-before-p03-fixed-objects-main1-6e4b4e37` recover到全新 `/Users/chad/dev/guradb-p03-ci-fixture-diagnostics`、分支 `codex/p03-ci-fixture-diagnostics`；clean原4d上先task-start，再cleanFF到b3dd。新task `616ed8ca962d427dbd1f0d4d68425c8f` 原base仍 `4d6baca888421d90f146679ef71b0e555fe60881`，checkpoint `checkpoints/20261021T093805Z-before-p03-ci-fixture-diagnostics-a1ee9f64`；旧55eb任务completed/旧树clean不动，不abandon或覆盖。新任务完整承接原P03与原base全部义务，不缩为五文件增量门禁。源码恢复序列SHA `85b0f84b62fc9296d671e933871dd78b8ea442d1d2f47466cabdb718ee2770e7`。

当前已知：两版PR12 CI均在验收functional函数的特殊PUT分类裸assert处失败，已有安全异常先构造但未传播，外层只写AssertionError因而无actualcode/status。准确位置为 `tests/storage_support/acceptance.py` 原153行，不是生产读取已经证实失败。三SDK锁版本一致，不继续无证据版本假说。经root独占授权的同bb05固定index/linux-amd64子manifest窄诊断，控制PUT成功、dot仍SignatureDoesNotMatch/403，source28不变且资源零剩余（OLDP06 `artifacts/p03-amd64-dot-diagnostic-20261021T0932Z/window-result.json` SHA `ec65cc26a7a086ab02d919d12f9fffa6463e3dd6f309e2474e4c9570b7bb8fbb`，实际SDKreport `faac95230bd51c8bdcb86af97df68d74c929348ffe164c09f4e65f3d8d90585f`）。它未复现完整Linux CI，不证明架构或SDK是根因。

先更新本节/用户leaf/场景表，再只改 `tests/storage_support/acceptance.py`：可抽fixture-only唯一特殊PUT helper，把原四case成功/错误分类集中；只有dot SignatureDoesNotMatch/403可返回negative分类，其余ClientError `raise FixturePutFailure from None`，让原外层driver写既有受限诊断。dot意外成功、非dot失败、缺固定版本仍失败。原negative-only描述符/unsupported_capability/0GET/output分支原义保留；没有第二套生产签名或请求语义。只新增 `tests/unit/test_fixed_object_fixture_put.py`，用真实botocore ClientError经过helper再穿driver失败artifact，覆盖400/404/非预期403/恶意SDK字段、三个合法key错误拒绝及dot意外成功/精确403负例；不改原单位用例。

作者只有上述helper、新unit和三leaf写域。shared导航/CI/harness/锁/coverage与全部生产P03模块保持b3dd；该先行SOURCE阶段尚无新venv/target或运行。源码完成后保存完整原base路径清单/模式/SHA与patch，再独立复核并另排运行窗口。所有旧FAIL/PASS和PR12失败状态保留，新补丁只修复诊断丢失，实际CI错误与根因仍未知；不能因本机403把后续CI或I1标通过。


本树首次定向单元窗口（2026-10-21）：独立新venv按三锁安装并pip check通过；`.venv/bin/python -m unittest -v tests.unit.test_fixed_object_fixture_put` 实际7项全部通过（unittest3.658s，外部3.810795s）。结果位于 `artifacts/p03-ci-fixture-diagnostics/unit-first-20261021T095157Z-790e530e/result.json` SHA `1c4d2676f5c6cb8d15ae5fb399439b3bb1c2864b9d6cc890cb4fc9d6e4a9024a`，window-result SHA `61911659d9ef5c05202725572b457654845ef1ead15491ed6429b1f6ee84d286`。39源码/5dirty/receipt/index前后未变，随后仅更新本三结果文档。单元使用真实ClientError类和mocked服务/driver环境，未运行实际S3/SDK网络、Rust或完整门禁；target仍不存在。原4d完整normalhook/post、私有raw保全、PR与精确main/双CI待验，PR12实际后端code/status与根因仍未知。
