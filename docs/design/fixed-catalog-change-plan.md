# 变更计划：P02 CF1-A 固定目录首片

状态：恢复树运行前34文件冻结下，26项针对性单元、全量232项Python测试/4028执行行零排除及真实PG七容量performance组件通过，独立语义和全部原件复核PASS；本次只更新结果文档，完整原base门禁、Rust、新functional/fault和提交/CI/main验收仍pending。历史先行合同与失败记录保留，最新证据见文末。

Git：`codex/p02-fixed-catalog`，worktree `/Users/chad/dev/guradb-p02-fixed-catalog`，起点 `4d6baca888421d90f146679ef71b0e555fe60881`，原树干净；task `08a01f79d8a347b0b429e072167318c3`，checkpoint `checkpoints/20261021T015356Z-before-p02-fixed-catalog-eee85479`。该起点的 CF1-A PR 双版本 CI、本地精确 main 十项门禁和真实双向互通已通过，main push run39528308712 的 Python3.11/3.14 也均 success，合同首片主线交付已闭合；真实 I1 仍待实现。

## 目标、范围和用户合同

落实[并行计划](../plans/2026-10-20-parallel-delivery.md) P02 的有限共同读子片，不完成整个 P02/I1。实现真实 PostgreSQL 18 持久目录：不可变完整目标登记、active-plan 发布、CAS/owner fencing、幂等及 unknown 对账，原子固定 view/授权/query lease，当前撤权和精确清理。所有公开值复用 CF1-A；目录只保存元数据。

支持/拒绝、容量和操作见先行[用户合同](../user/fixed-catalog.md)，验收见[场景表](fixed-catalog-scenarios.md)。契约 authority 为显式 trusted fixture registry，必须在每次新效应和读授权时验证当前保护；不能由此声称真实对象/源/索引保护或完整 I1。legacy catalog/jobs/query/gateway、源 writer、GC、训练、schema 迁移、HA/PITR 均不在本片。

初始先行合同与 cf1a_pg/codec/store/auth/schema 基础由 root 编写，交权当时全部尚未执行验证。2026-10-21 root 串行交权后，P00/P06 作者临时承接本树唯一写权限，继续 facade/admin/mutation/binding/单测与真实 driver，root 停写并独立审查；正式停写交回前不同时修改 P06 树。文件域为 `modules/catalog/cf1a_*.py`、`cf1a_schema.sql`、专用 `tests/unit/test_cf1a_catalog*.py`、`tests/catalog_support/`、`scripts/fixed_catalog_acceptance.py`、本片文档/ADR0021。root 后续串行负责 harness driver 接线、用户手册导航和 tracker；其他模块作者不能改热点。不得改 common、现有 control/jobs/schema、依赖锁或覆盖政策。

## 不变量和持久布局

关联 ADR0004/0007/0016/0019/0020，拟议 ADR0021；INV-001/003/004/005/006/007/008/009/010/011/012。实际 `plan` 输出另存 artifacts，不能用登记不变量证明覆盖。

独立 `gura_cf1a` version 1；特权 provision 先创建 globally unique dataset 行，tenant 不可变且 ID 不可重分配，再以该行锁串行 mutation、reconcile、grant/revoke、owner 交接、bind/reauthorize/release。固定锁序 dataset→授权→不可变 target→query/lease；无 missing-row gap-lock 假设。canonical CF1-A envelope/payload bytes 与摘要用 bytea 保存，不经 JSONB 重序列化；lookup 列从 strict decode 派生并在读取时交叉核对。

data head 与 active publication plan 分开。计划冻结完整 target、注册 op/generation、owner 身份/epoch、此前 published 指针、预留 publish generation/sequence 和状态。g→register g+1→publish g+2，两步 target payload hash 不变且 op ID 不同；register 前同时预检 g+2 与 sequence+1 的安全整数空间。publish 不能补 artifact；旧计划不能刷新 CAS 后复活。同 head 重建保持原 revision parents；新 head 才要求 exact-current parent。register 仅可信操作者，worker publish delegation 绑定一个精确已登记计划。旧 published target、pin、terminal receipt 不随新 head 改写。

不同摘要域明确固定：request=canonical intent payload，target=canonical ReadDescriptors payload，issued binding/batch context=完整 Contract envelope。MutationReceipt rejected 仅 A 三种错误码且 result 为空；所有状态 reconcile_ref 非空。`check_receipt=True` 只表示 determinate。当前授权在 replay 输出前检查，但已应用回执重放先于新效应 CAS/active-plan/source-proof 检查，不重做副作用或授予读权。

mutation effect 与 terminal receipt 同事务；所有迟到 writer 在 dataset 锁后重读回执。unknown 不自动重放。无 durable claim 的 absent reconcile 仅可信管理员且同时持有 reconcile 和原 register/publish action 可 terminalize 为 rejected/conflict tombstone；管理员角色不覆盖 live grant。空间不足保持错误/unknown，不能假报未发生。bind fingerprint 固定为完整 canonical BindRequest envelope SHA，并持久核对可信 principal/subject/delegation，不能只取部分业务字段；所有 live/released/expired query 均计入1024身份容量。丢响应重试不跟随新的 published；精确 binding bytes 防预算/租约篡改。已知回执/同 query 重放/精确 release 不新增身份计数。release 不先调用 validate_access，可信 owner/cleanup 可清理已撤权或到期 lease。

admission deadline 在连接/锁等待前固定，PG statement/lock 和 authority 调用消耗原有时间；TTL/expiry 严格符合 A 等式，锁/authority 返回后读取 fresh 时刻，不能用 transaction_timestamp/now() 代替。普通 Psycopg connect_timeout 最低2秒且 socket 等待不等于 whole deadline，不能据此宣称有界；拟用锁定 Psycopg 的公开 pq 非阻塞连接/Connection wait 适配，在同一 monotonic deadline 下等待握手、SQL、commit，超时关闭该连接，commit 阶段失败保留 unknown。仅本机显式IPv4/无TLS支持域；实际黑洞握手与暂停PG/锁竞争必须证明清理和期限。可信 fixture authority 为有界本地 registry，不借任意阻塞 callback 声称可抢占外部调用。安全整数溢出在 effect 前 fail closed。行数和8MiB持久canonical元数据容量冻结于用户合同，不自动扩容/删 tombstone。所有源保护检查须可信当前 authority；没有跨 PG/外部源原子事务声明。

## 文档先行、实施和恢复

接续新增管理副作用合同先于代码：严格 immutable AdminIntent（private version1，actor tenant/subject/delegation、dataset/op/action/全部参数）与 frozen canonical AdminResult；provision/grant/revoke/rotate_owner 不借用 A RegisterIntent。operations 新增 kind 分类，admin 与 A 回执共用512/8MiB。已知 replay 先于quota和副作用；原revoke迟到重放不重撤新grant。provision 全局锁、其余dataset锁，effect/result同事务；admin_status absent只unknown，原intent在同锁重试仅应用一次，不做absent终结。grant/revoke单调policy epoch、rotate仅owner epoch且fence未发布计划。initialize静态DDL幂等。先行增量与接续前基础源码指纹保存 artifacts/fixed-catalog/handoff-docs-first.*，不把root先行摘要当新增行为通过证据。

先创建用户章节、本计划、场景表与提案 ADR，再保存 `artifacts/fixed-catalog/docs-first.patch` 和摘要，之后才写行为。拟按持久 codec/store→admin/auth→mutation→binding/port→独立测试/真实 driver 的职责拆分，每源文件不超过600行。小步单元和真实 PG 验证后独立审查；受控运行窗口由 root 排队，不与别包性能/故障/coverage 重叠。

只新增 schema，无用户业务数据迁移或旧 pointer 自动切换。回退关闭新 adapter、保留目录/回执/tombstone/pin，并对账 unknown；不 drop 表或重用 ID。旧PG备份恢复没有自动检测/外部fence，本片只验证restart；人工quarantine必须停用整个adapter含mutation，外部恢复对账属于后续P18。需要恢复时保留日志/完整含 untracked 的 diff，在新目录从起始 checkpoint recover；代码恢复不补偿已提交 PG 状态，独立对账。首次失败保留假设和 seed，两次无新证据失败停止盲试。

## 验证合同

独立固定 fixture 含完整 int8、NULL、非 ASCII/escaped NUL 描述值。真实 PG18 pinned image、独立连接和 SQL 状态查询检验：CAS 并发、旧计划刷新 CAS、同 head reindex、新 revision、owner takeover、跨租户/subject/delegation、worker register 禁止、receipt 幂等/指纹冲突、提交前后响应丢失、absent reconcile tombstone 与迟到请求、对账响应丢失、bind 响应丢失并发新发布、撤权/regrant、旧 view、伪造 binding、精确 lease 清理、restart 持久性、容量/安全整数/损坏行 fail closed。提交后的故障注入模拟客户端未收到结果，PG effect 本身真实；不宣称 PG wire 故障认证。

truth 直接核 PG 行/计数/指针/不可变 bytes 与独立预期，不以本实现 replay 为唯一 oracle。unit/contract 仍严格100%适用行，旧排除不改；SQL 锁/commit 的实际证据由真实 PG 用例给出。driver 固定 seed 20261021、最多16个 dataset 的小型元数据、30秒内 query lease、120秒组件运行上限；记录新/复用连接、PG restart、请求次数/elapsed/元数据字节与机器镜像摘要。这里没有产品 QPS/p99 或业务质量 baseline。

driver要求仓库内新输出目录且拒绝复用；运行前后采集完整源码/commit、锁、Python/Psycopg/PG镜像与实际target/binding输入和产物SHA。异常也在finally保存失败状态/trace/服务日志/前后manifest并清理自己服务，源码变化或超120秒不得返回pass。分functional/performance/fault模式仅为门禁选择，不复用旧结果；性能为同一小规模组件的实际观察，OS/PG缓存不受控必须披露。SQLite单测仅验证SQL语义，不能替代实际PG、非阻塞黑洞/暂停/锁等待与commit故障。

初始、hook、原始 base clean-head check/task-finish、当前 PR 双 CI、expected-head merge、精确 main 范围 check/checkpoint 与 main push CI 均按仓库流程，不跳过 pending/失败。raw component trace 单独归档；harness archive 不自动复制所有外部输入。

## 历史结果和复核

当前bb4c7f98源码清单的17项SQLite语义/mock单元在0.127s通过，含root新增提交中断与cleanup负例；不替代PG。首次Python-only全量221测试通过，但4020/4028行、零排除，exit1，原报告`artifacts/fixed-catalog/python-initial-20261021T0316/`与完整日志保留。八个未执行行分别为精确worker publish授权、reauthorize/release/reconcile的unknown分支和预检非conflict失败传播。先记录此失败再仅补有意义负例：worker错计划无副作用/正确计划发布；读授权未知不能回传epoch、release丢结果按原lease重试；absent对账提交未知不可假拒绝；g+2空间不足不生成rejected receipt或部分身份。生产、阈值及排除均不变，新指纹复核后再获窗运行。

plan_audit第三方只读审查发现：Store仅捕获Exception，COMMIT尝试后的KeyboardInterrupt/SystemExit可逃逸unknown转换，finally close也可能遮蔽该状态。root先更新用户合同再修该边界，补提交前中断传播、提交中/后中断unknown及close失败负例。原24文件交回清单SHA为dd0217a98f7567d8b6e72ef769e1ad259d7a202fddab7725688e02ce4dcefc01，所有初稿尚未执行，不能引用该清单为修后通过。

审查同时收紧未执行driver的证据合同：100ms握手/SQL/锁预算原750ms返回断言不足，改为最多50ms明确测量容差，报告原deadline/实际return/连接关闭；这不宣称100ms硬实时响应SLO。blackhole必须在服务stop之前独立观察客户端EOF。另补真实PG暂停于COMMIT调用前，在原5秒事务deadline内关闭客户端并返回unknown，50ms返回测量容差；恢复PG后独立SQL核对effect与receipt原子性，再重试同一admin intent验证恰好一次。服务恢复注入成本单列，不混为客户端关闭成本。既有真实commit之后抛错只证明客户端边界响应丢失注入，不冒称真实TCP ACK丢失。

交回初稿时，root先行基础与接续 facade/admin/mutation/binding、SQLite语义unit、公开非阻塞transport mock unit及真实PG组件driver全部尚未执行；后续17项局部通过与Python覆盖失败见本节前述记录。接续作者在保存交回manifest后停止本树写入，由root恢复唯一写者并独立复核；root原PG/store基础另由plan_audit第三方只读复核。真实PG、修后全量覆盖、组件测量/fault trace、正式门禁与最终commit仍pending，不引用CF1-A/旧组件通过作为本片通过。SQLite不证明PG锁、期限或提交语义；真实driver文件存在不等于已接线或已验收。

## 验收证据生命周期修订（待实现、待运行）

2026-10-21 p01_oracles独立只读审查发现三项实质缺口，root认可后整树串行交权给该作者，root停止本树写入：driver先import生产/fixture再采source-before，存在已加载旧代码却绑定新文件SHA的窗口；docker logs非零未判失败，可能缺真实服务日志仍pass；finally先写actual-inputs，I/O失败会跳过owned PG清理。审查时driver/support与04清单一致，root28文件接线清单 `3941792f3ffbfeea5e8d91d2f512297047c06c8386c381bef7814dad68cde96b` 已另独立复核；本次修订不沿用旧225测试/4028覆盖或其它旧identity为新checkout结果。

仅调整验收入口和证据生命周期：先捕获源码/fixture/锁身份，再在同一try/finally内普通静态import生产/support；import失败也保留前后身份和失败。证据写入错误与日志提取非零均保持失败，尽可能保存有界类别/返回码，任何证据I/O失败都仍尝试清理自己唯一命名的容器。日志提取失败文本单独命名，不能当作真实postgres.log；清理失败同样不转绿。before/after完整身份与原120秒上限不变，不以导入或诊断异常修改目录生产行为。

connections计量精确标为成功adapter connect，不包括失败握手、独立SQL oracle连接或所有PG流量；不由该字段推导全局请求/网络成本。补三个有意义的独立验收负例：首次身份之后导入阶段改变源码并失败不能假绑定；日志提取非零即使移除成功也不能pass；actual-inputs写失败仍尝试owned清理并保存失败。可使用小型验收lifecycle helper，不新增依赖、不改生产/原PG工作集/预算/锁/共享接线/覆盖政策。先保存本轮docs-first patch与新精确diff/manifest，独立源码复核后再获受控运行窗；当前SOURCEONLY。

root源码复核发现新负例的临时ROOT未resolve：macOS临时目录可能以/var别名给出，而driver按/private/var规范化output，is_relative_to会在被测边界前拒绝。此为未运行的源码发现；仅测试setUp规范化ROOT，不改被测断言、driver或共享接线。修后重新冻结29文件身份，仍未运行，不借旧覆盖结果宣称通过。


## 原树局部证据与共享门禁接线（历史）

新增四组负例经作者外独立复核后，在原24文件清单 `af3d3d93c612b0e10cd2301d11a1fe6debaaff44ce3857c77cf6e6fe5e02931a` 上运行：21项针对性单元0.156s通过，Python全量225项19.936s通过，4028/4028执行行、missing0/excluded0；`artifacts/fixed-catalog/negative-unit-coverage-20261021T0322/result.json` 与 `python-negatives-20261021T0322/` 为实际记录。root已核对全部24SHA、所有日志SHA和identity前后相同、当前checkout `677fa434dc5e2854a969db3fa4edef7b35c523777098cd70df58e1777db351aa`。保留首次8行缺口失败，PyIceberg解码器回退warning明确记录。这些结果不证明PG、Rust或文档更新后的新checkout通过。

root继续本树唯一写权限，先记录以下内部验证接线合同，再修改共享harness：在现有functional、performance-smoke、stability-component各追加真实 `fixed_catalog_acceptance.py` 的functional/performance/fault命令，输出到同次新run子目录；已有命令、suite时限、完整performance/stability/soak的planned状态、strict100%与21条Rust排除保持。Python静态检查补driver及catalog_support。独立修改该driver或support代码也必须选中Python、功能、组件成本、组件故障与覆盖门禁；support的纯Markdown仍按文档处理。补防漏选负例，不为本改动引入额外产品入口、参数或依赖。Psycopg已经锁定且在architecture允许表，不添加依赖例外。

用户导航只标注当前组件候选与真实PG待验收；追踪同步已经闭合的PR9及本片实际owner/范围，不把原方案依赖误写成阻止当前编码。共享接线须由作者外只读复核后才能进入真实PG和整仓检查。driver/support仍冻结等待独立源码与证据绑定审查，任何发现先记录后改，不将SQLite或mock通过代替真实PG。


## 首次真实 PG 重启失败与 fixture 修订（源码前记录）

首次真实functional在16.914504s失败，未继续成本/故障。原29文件冻结清单74286bcd保持，source-before/after一致；真实固定绑定、并发CAS/owner fencing和独立SQL字节核对已执行，但整体不通过。原始失败在 artifacts/fixed-catalog/reviewed-functional-20261021T042659Z/driver/：report SHA5955510e134a00540c563d9fd6b7ad12bcf6f5d02c8e4eaad3d1a152c0ee6027，PG日志确认重启后服务ready，而原DSN连接仍失败；本次owned容器已清理。

独立聚焦实验使用同pinned PG18、新唯一容器，重启前host动态port58969可SELECT1，重启后实际映射58982；旧端点OperationalError，新端点SELECT1成功。用时1.399463s，owned容器删除且确认不存在。证据为worker worktree artifacts/p02-port-probe/result.json，SHA e6262594c56694fdba4bdfcffc29c46876557717a0edf949e91fe3f85ced57af。root已实际阅读该实验；支持driver沿用旧动态端点的根因，不能把原失败改成通过。

先记录最小验收fixture修订再改代码：只为本机测试选择一个当前空闲loopback port，显式请求Docker固定发布；发布前不声称端口一直被保留，若竞争占用须正常失败并清理。报告请求/首次/重启后三个实际port，必须相等才能验证同DSN重启持久性；不默默改DSN或重新建目录来绕过断言。新增负例模拟重启映射异常变化必须失败并仍清理。生产目录adapter、实际PG操作/容量/120秒组件上限/100ms等待与50ms容差、锁依赖/共享CI接线不改，旧228/4028证据不冒充新checkout。源修订须独立review后重新运行局部单元/Python及真实functional，再依次成本/故障，不盲重跑旧SHA。


## 新目录恢复与当时直接证据边界（先行合同）

原dirty树、task08a及首次重启FAIL595551/聚焦port实验/修后local和真实PG原件保留。由原checkpoint在新 `/Users/chad/dev/guradb-p02-fixed-catalog-recovered`、branch `codex/p02-fixed-catalog-recovery` 恢复，clean原4d先task-start `5d1ffe780f3b4001a706a0d96a925a77`、checkpoint `checkpoints/20261021T051854Z-before-p02-fixed-catalog-recovery-948b9845`，再FF17d。23非共享bytes/modes/SHA等c480新备份98b5a986，6共享留main由root串行合成；原任务待完整29义务核验后仅abandon保留现场，不标完成。新receipt仍原4d，全部plan/check/hook/postcommit/task-finish不得缩到17d。

PR10 merge17d已完成精确main五gate/report6d0e4932/checkpoint044927及PR39544118302/main39545360623两Python版本CI。root先记录此内部验收接线再改共享源码：原6共享P02增量在17d底合成，保留900 coverage watchdog和全部worker修复；PG3driver增加900+300+300，10ready29commands加原600秒=16320秒272分钟，普通job275/release360。既有负例改用当前有效change分支，仅把release替367测试hosted上限，不改validator/真实预算/strict/21排除/产品或100ms+50ms、5s+50ms容差。上游增加命令须重算，不能沿用275。此修订没有生产行为或格式变化。

旧29冻结c480上，25针对性unit/229Python tests及4028/4028零排除通过；真实PG18 functional/performance/fault报告依次2385c100、8c8e7f81、23cc9fc8，完整原件位于旧树 artifacts/fixed-catalog/reviewed-functional-20261021T045443Z、reviewed-performance-20261021T045506Z、reviewed-fault-20261021T045540Z。独立raw审查 b68bff785afbe6f5e4788b375ecae653e3f0a80888c06326c1deee3420a02445 实际核source、全部canonical记录/字节、端口、固定binding/CAS/unknown和原deadline+清理，观测场景PASS；原595551整体FAIL不改。通过仍只绑定旧树/c480，不作为新checkout/fullharness或真实保护/I1/HA证明。

FC10尚有直接证据缺口：实际打满只有512个共享operations和8MiB总字节；16dataset、64grant、256identity、128target、1024query尚未逐项触边。通用Store.quota和100%行覆盖不能代替这些边界。后续先更新用户场景，再追加真实PG适配调用的quota验收，保留全部原512/字节/功能/故障输入与预算；联合上限先到必须明确记录，不缩负载规避。查询需同时证明live/released/expired均计数、满额同query重放/精确release不新收费或腾身份。当前只共享源码恢复待独立复核，未安装本树依赖/测试/完整门禁/提交或PR。
# FC10 完整行容量补证（源码前历史合同，结果见下节）

本段在追加验收代码之前保存。旧树c480的25项单元、229项Python测试/4028执行行零排除及三PG driver已有独立raw复核b68bff785afbe6f5e4788b375ecae653e3f0a80888c06326c1deee3420a02445，但其FC10只实际达到512operation与8MiB，16dataset/64grant/256identity/128target/1024query仍缺直接边界证据。旧FAIL/PASS与snapshot保留，不移作新恢复树通过。

此次只追加`tests/catalog_support`有界fixture/SQL账本helper和PG quota场景，在`fixed_catalog_acceptance.py`的performance模式追加调用；生产10模块/schema、common/A、共享policy/selector/CI/阈值/覆盖规则均不变。必要时只适配既有driver生命周期unit的注入fixture，不能删旧输入或跳过真实调用。新源每份不超过600行。

1. 授权quota：独立dataset真实provision和64次grant，独立字面预期64行/65operation/epoch65；新65拒绝前后全账本不变。满额同op重放不计费；更新首个已有键后64行/66operation/epoch66，再重放旧结果不得退回新grant。
2. 身份quota：固定resource/revision/source，第一目标125个小artifact给129身份，第二126个新artifact及新view给256；只有2target/6operation。第三目标复用已知artifact，仅新view尝试257时拒绝。A允许不同artifact_id共享同kind/model且共享完全相同的物理ObjectRef描述符；这只是可信保护fixture的目录容量验证，不宣称P06物理文件支持多身份。
3. 目标quota：固定同revision/source/artifact，只新view；逐次register/publish128次后132identity/128target/258operation/generation256。第129目标应resource_limit，不能先撞256identity或8MiB。两类case都核旧已知receipt满额重放，并独立核新目标、operation和metadata不存在。
4. Query quota：合法紧凑scan-only目标避免先碰字节quota；逐一真实bind1024次，无SQL灌入。首个短TTL、第二项立即释放、最后项在满额前才创建为live，其余每项不超过原30秒。以真实PG时间核过期，最多1秒有界等待计入原120秒，不patch时钟、不续租。live完整request原bytes重放、expired/released不能revive、新1025拒绝；expired/cleanup/repeated exact release不腾身份；篡改或异主lease无效；先完成live replay及quota断言，再撤read grant验证owner cleanup，避免epoch变化污染live重放前提。
5. 最后才通过公开provision填满16dataset；已有scenario数据保留，known provision/status满额返回原bytes，新17拒绝后独立全局SQL无孤儿或计费变化。重启场景只重开已有dataset，不受填满影响。

独立SQL账本按实际bytes逐项重算canonical/摘要和metadata总量，不导入生产LIMITS生成期待值。每个target/request先核canonical<1MiB，数组≤128；每个阶段核其它quota与8MiB有余量，跨quota先失败不能认证目标边界。全部新工作计入原120秒，保留原512operation/8MiB完整成本负载以及100ms/5秒故障门限和50ms测量容差；若实际超预算先保留失败定位，不能删负载或抬阈值。

当前仅source-only追加，独立venv/新unit/Python覆盖/真实PG与完整原4d门禁均未执行；先冻结新全源清单交root独立审查，获得独占窗口后才运行。新receipt仍以4d固定原始范围，不能以旧c480局部结果或17d工具修复替代本次验收。

## 恢复树 FC10 七容量的实际结果与独立复核

本节只追加结果说明，不改生产、helper、driver、测试、共享接线、预算、覆盖或receipt。运行前34文件冻结清单为 `artifacts/fixed-catalog-recovery/quota-source/review-manifest.json`，SHA-256 `2432c634478c7327786b5b42ff85aa89002c24855a56b3f217e74cde0d156955`。独立源码复核后，在本树新建venv、按三份锁安装并pip check，再在唯一受控窗口运行新单元、全量Python覆盖和真实PG performance；各阶段source-before/after相同。上述历史“未运行”记录仅描述当时状态，旧FAIL/PASS原件未覆盖或改判。

恢复树为 `/Users/chad/dev/guradb-p02-fixed-catalog-recovered`，branch `codex/p02-fixed-catalog-recovery`，active task `5d1ffe780f3b4001a706a0d96a925a77`，原base仍 `4d6baca888421d90f146679ef71b0e555fe60881`，本轮HEAD `17d66c66a067eebe73280ce8d3488fb4f7cdcfe9`。旧08a任务在完整义务承接后仅abandon，旧dirty树、失败和raw全部保留；没有缩小新任务原始范围。

实际结果：26项针对性单元PASS；完整Python 232项测试PASS，4028/4028适用执行行、missing0/excluded0；真实PG18 performance PASS，31.526968秒，成功提取服务日志并清理owned容器，返回码均0。原512operation/8MiB完整成本负载保留，新增五类行容量全部实测，共七条必要容量trace；精确计数、原子拒绝、重放和cleanup语义见[FC10结果表](fixed-catalog-scenarios.md#恢复树七项容量实测)。120秒组件上限、100ms/5秒故障合同及单列50ms测量容差未调整；本轮没有重新运行独立fault模式。

本轮原始目录为 `artifacts/fixed-catalog-recovery/component-first-20261021T061507Z/`。`window-result.json` SHA-256 `704167d301be3478fcbcdb3903c52904032722526908b863745a5c033c6c3c3a`；`performance/report.json` SHA-256 `c49472bcd8e30b54e99f15c1dabd6762f0bec0a46ba1def8bb4cd16a8be6471c`；原件账本 `retained-evidence-manifest.json` SHA-256 `7ba0f142890150ce70f28db6ca5e9ad538ef163f8accf889c6d1eb300d5091a8`。精确argv、stdout/stderr、exit/wall、锁/环境/实际PG记录及前后源身份均在该目录，不复用旧c480测量。

作者外plan_audit独立复核结论PASS：worker树 `artifacts/p02-component-review/quota-runtime/combined-review.json` SHA-256 `03b40a4655a52ff5e4e571f4b91f2d8d2dfe4d37a9ec0a34338d28d4c85fdbc4`。其中语义审计核十份canonical SQL witness、独立字面预期、跨quota余量及无部分副作用；原件审计逐份读取4516文件/4509 canonical body，复核其摘要、字节、target/identity、query/request/binding/pin/授权/TTL关联。`raw-audit.json` SHA-256 `19852131f99ff89a6e996a3ced74e1d621a9a2846c662fa54face78628d641e0`，`raw-actual-manifest.json` SHA-256 `857c7f0442bcf4b2c3f99e943fb95952d81439b361a93dc119045faebcea4604`。被更新/删除的两条历史grant仅从独立字面字段重建验证历史witness的SHA/长度，不包含在4509份实际最终body中，也不是原始历史bytes证据。

组件环境为本机PG18可信fixture，每操作新adapter连接，OS/PG缓存未控制；未认证冷缓存、native PG peak RSS、产品QPS/p99、云/HA/P18或真实P03/P04/P06的I1配对。此次文档结果修订后另存唯一新34文件清单及三文档增量；旧2432清单和其运行证据保持原义。新冻结下完整原4d harness、Rust、新functional/fault模式、hook/提交后原base检查、task-finish/最终原件归档、PR双CI/精确main检查及main CI仍pending，等待root串行安排，不以局部通过标完成。

root在独立核对三份结果文档及03b40a46实际审查记录后接收whole本树唯一写权，仅同步用户入口和实施追踪两处旧FC10状态。本段和两导航不改变生产、测试、容量、时限、receipt或共享门禁；运行前2432与作者三doc更新7c0ff均分别保留，新冻结仍未运行。

## clean主线接续的内部状态（2026-10-21创建时）

PR11已完整闭合到1e4f6a6c26eb28982f4b61cc75aa05e290211809：PR39555312514及main39558459736两Python版本均SUCCESS，精确17d→merge本地9suite/24命令报告bc049da2、checkpoint071032通过，root对834raw三端实际复核72e21975。它仅为legacy私有Compiler提取，不代表P05 CF1-A或I1。

P02新接续树/Users/chad/dev/guradb-p02-fixed-catalog-main1，branch codex/p02-fixed-catalog-main1，clean原4d先task-startb826fc2af8cf4ebcbf2142ec6b6913f8/checkpoint checkpoints/20261021T071248Z-before-p02-fixed-catalog-main1-d960ee3c，再cleanFF1e4。34源码/模式实际等09856备份fad89，原base仍完整4d，index为空，P05五上游路径无交集且当前字节保留。恢复记录b5d63c5a与真实操作/时序在本树artifacts/fixed-catalog-main1/source-recovery-20261021T071247Z/。root已逐实物复核全部34/receipt/上游，随后仅追加本内部状态与实施追踪，无新用户行为；没有把old17d的2432组件通过挪为此新checkout通过。

旧5d1恢复树/08a原树源码及raw、首次FAIL与后续局部PASS保持原义；旧5d1只有完整承接确认后才abandon，不标完成。新树matchingvenv/实际原4d完整plan、正常hook作为首次新checkout完整检查、提交后原4d freshpost及独立审查/task-finish/最终raw归档/PR和主线验收均pending。真实P03/P04/P06保护、PG HA/P18及I1仍未配对；后续upstream增加driver需root从实际policy重新合成预算，不复制另一分支的whole policy或缩原base。
