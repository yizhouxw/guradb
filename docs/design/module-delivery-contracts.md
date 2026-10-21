# 模块交付合同：边界、owner 与运行时权威

2026-10-21。执行[策略 v2](../plans/2026-10-21-modular-delivery-v2.md)与[ADR0022](../decisions/0022-module-delivery-and-validation-levels.md)；细粒度验收见[需求矩阵](../product/requirements-v2.md)。本合同确定下一轮职责与交接，不改变机器依赖 DAG 或声称尚未运行的实现通过。旧 P00–P20 保留追溯，I1/I2/I3、G1–G5 最终义务保留。

## 1. 当前实物与下一出口

| 实物 | 可直接复用的稳定面 | 尚不能声称 |
| --- | --- | --- |
| CF1-A Rust/Python canonical/schema/ports | 已有固定 binding、ReadBatch、CandidateBatch、登记/发布/精确 lease 合同 | 同步 trait 本身不证明父取消、失败 Usage 或真实跨语言执行 |
| P02 真实 PG 目录候选 | register/publish CAS、绑定、撤权、精确 pin、unknown 对账及七类容量已形成组件证据；后续精确 commit/CI 由 ROOT 进度账决定 | 不等于 PG→P03 当前授权已接线；当前跨模块 reauthorize 的父期限/取消闭包仍缺真实配对证明，需父控制适配 |
| P03 固定对象读 | 固定 VersionId/完整性/累计 scope/真实 socket 取消已实现；direct fixture 42 文件 a828 候选已独审 | PR13 历史双 CI 失败保留；新首窗仅在只读镜像身份预检失败（默认现为 arm64，旧 runner 要求 amd64），尚未安装/测试/启动服务，不能挪用诊断为 PASS |
| P04 固定源 | ec182 历史真实 P03/S3/Parquet 三组组件与独立真值已过；窄格式、完整首次 scan、SourceReadPort | 新 shared 接线/最终 head 单独验；不是一般 Parquet/按需 provider/写入 |
| P05 Rust | A1a 唯一 SQL core 与 26 目标 unit/strict 既有证据；5faf M1 原 22 新定义 | M1 完整 Value 预约 R2，a925 PARTIAL 保留待独审/编译；不能当真实 Source 或 I1 |
| P06 固定物理索引 | BM25/3D squared_l2 真文件、独立数学/定位/11 行真值和组件证据 | 真实 P03/P04/PG 配对、located-build 输入及候选回表未接通 |
| P08 | 三 leaf 正式入口设计候选 | 新 HTTP/PG 查询入口尚未实现；旧 alpha 不充当新共同入口 |

状态由模块功能点记录 `designed/source_reviewed/component_passed/paired/system_passed/released`，每项附精确源与报告；一项不可替代下一项。上表是本次小量源码/已收交接的事实摘要，未重跑历史证据，未补称任何 PR/main 闭合。

## 2. 模块合同与唯一开发 owner

下表 owner 是本轮模块开发 DRI，不表示同时开工；具体文件写权必须由 ROOT 逐树交接，当前保留树不被新职责自动覆盖。P00 完成 harness 后才接 query；plan_audit 完成架构复核后可临时兼任 storage/connectors 实现，其自写部分改由 P00/ROOT 独审。P01 保持需求/独立真值，ROOT 保持 PM/组合与共享协调；最多两项行为实现在制，留一个独立审查槽，不能让四个角色都变成管理而无人开发。

| 模块 / 唯一 owner | 职责；输入 → 输出 | 错误与依赖边界 | 本轮资源与验收出口 |
| --- | --- | --- | --- |
| common / P00 | 值、schema、canonical、低层 ports；声明 → 已验证不可变 Contract | allowed=[]；未知版本/能力、类型/NULL/规范编码显式拒绝；不做 PG/S3/SQL 编排 | A envelope≤1MiB/TTL≤30s 等既有约束；全 golden/rejection 双语言真实互通+模块严格100% |
| catalog / P00 | 身份/授权、revision/view、pin、登记/发布与恢复状态；可信 principal+固定意图 → binding/receipt/epoch | 仅 common/storage；源提交不属于目录事务；保留 conflict/unauthorized/outcome_unknown，receipt 不授予读权限 | 真 PG18；原16dataset/64grant/256identity/128target/512op/1024query/8MiB及120s容量序列不降；锁/暂停/COMMIT未知/迟到原请求实测 |
| storage / plan_audit | 固定对象寻址、传输、完整性与缓存；binding+ObjectRef+父控制 → bytes+真实账 | 仅 common；不解释 Parquet/SQL、决定租户权限或 GC 资格；missing/corrupt/unavailable/auth/cancel/deadline 分开 | 真固定 Seaweed/S3；原8MiB输入/256KiB cache/≤3attempt、700ms停顿和100ms取消目标保留；冷/暖、失败 attempt 与清理分别核 |
| connectors / plan_audit | 格式/源版本能力、field ID 映射、稳定身份、批次；固定 SourceVersion+对象 port → ReadBatch/源回执 | common/storage；不重绑 published，不发 view；unsupported codec/delete/schema 不静默跳过 | P04 真对象+独立 PyArrow writer/reader；4文件/16rowgroup/1000行/4MiB输入/8MiB解码、64行页/768KiB封包、页1s/cohort5s/RSS512MiB保留 |
| index / P00 | 固定源派生物、覆盖/模型/ID映射与候选；batch/config → artifact；IndexQuery → candidates | common/storage；不拥有目录发布/业务写，不把 locator 当身份，缺覆盖不得 complete | 真文件/实际算法，原100行/单shard/1MiB、build5s/query1s/RSS512MiB保留；独立分数/排序/NULL/损坏/全覆盖，ANN/Graph另立功能点 |
| query / P00 | 唯一 parser/Compiler/关系和检索选择、Arrow/DF执行/回表；固定binding+typed request+ports → typed result+lineage | common/catalog/storage/connectors/index/cluster；不另造授权/最新目录/SQL parser；完整输入与未知失败账不抹零 | 真 Arrow/DF50.3；保留8192行/32批、完整int8/NULL/参数、输入32MiB/Arrow64MiB/DF32MiB/结果2MiB及1000行宿主cap；联合父预算更小者优先，RSS另测 |
| cluster / plan_audit（I1仅监督私有本机 bridge） | 分配/取消/背压/worker生命周期；可信任务 → 带 attempt 的回执 | common/storage；不能解释 SQL/排名/目录授权；unknown attempt 不能免费重试 | I1仅本机独占进程组/有界 IPC；硬停止须 wait/reap、晚到/退出/失败计费实测。真实三机/TLS/调度仍单独任务 |
| gateway / ROOT | HTTP/PG wire、认证、会话、参数映射、请求生命周期；认证请求 → 同一个 query 调用 | common/query/catalog/cluster；不增第二 SQL/检索语义，不代理用户 SQL 到元数据库 | 新入口真 HTTP/psql/Psycopg、SQLSTATE/NULL/参数/撤权/取消；旧 alpha 显式回归；端点名在 P08 小合同冻结 |
| client-api/CLI/MCP / ROOT | 同一版本远程合同的薄封装 | client-api只依赖common，cli/mcp仅common/client-api；不得读内部PG/索引 | 与真实gateway成对测试；相同错误、参数与能力发现；不为首个真实SQL链路等待全部客户端 |

表中旧 cap 是有限组件边界，**不是可叠加的父预算或产品规模承诺**。query当前宿主10秒与A更小期限不变，新入口总时限从排队/绑定前开始，子预算只能缩短；缺少某项测量仍为 missing。新增导入/同步/训练各有独立参数、吞吐、延迟、恢复子需求，由 P01矩阵→对应模块 owner；不能用上述窄 reader 范围代替。

## 3. 共享文件、合同与交权

| 共享面 | 唯一写 owner / 必要复核与消费者 |
| --- | --- |
| CF1-A维护、B/C新增、api共同schema/golden/Rust-Python映射 | P00；架构师审核语义与版本，P01审核正负真值；架构师自写设计由 ROOT/P01 审。生成物同一变更，禁止下游私补安全字段。A已冻结部分不为 bridge 随意升级 |
| PG持久schema/迁移 | catalog owner P00；ROOT排独占迁移窗，connectors/index只能交回执，不能直接写表。B/C只冻结下一具体消费必需子合同，不再等全批设计完 |
| Cargo/Python locks、根workspace/lib主接线、API主文档、全局日志配置 | ROOT；模块提交精确依赖/接线 delta，ROOT串行合成，不复制整份旧文件。锁变更必须实际解析/构建与受影响模块回归 |
| harness/policy/CI/coverage工具 | P00实施；plan_audit非作者独审；ROOT接权整合。产品预算、strict100%/原21行有限排除与planned发布义务不可借选择器调整改低 |
| 组合入口、进程桥装配、跨模块场景、系统基准 | ROOT；provider和executor实现仍归各模块，组合根不复制业务语义。私有bridge协议架构评审后由ROOT指定单一作者 |
| 需求矩阵/独立oracle/业务性能目标 | P01；修改模块负载/语义需owner+独审，不因实现方便删功能或降低规模 |

每次交接最小包：commit或SOURCE指纹、具体文件/mode、合同版本/能力与不支持项、可消费接口、真实后端证据与fake边界、未结风险、当前receipt、下一配对命令/负责人。接收者验SHA后显式接权；同文件仅一个writer。普通源码交接不要求复制/哈希所有历史 profile，保存本次所需源、清单与安全原件即可；大证据仅在其测量/最终归档边界核验，依引用保留。

## 4. Rust/Python：单一权威与退出

- **Rust现在唯一语义核心**：SQL解析/类型/NULL/参数/过滤/排序/投影、Arrow/DF执行、最终选择与lineage；Python不得新增“临时SQL解释器”。HTTP/PG只映射到同一Rustfacade。关系/聚合/关联等不支持AST保持显式拒绝，按P01细化矩阵逐项扩展。
- **Python过渡权威**：现有CF1-A PG adapter、固定对象传输、窄Parquet reader、BM25/精确向量实现是各自已实现范围的唯一运行权威。I1优先真实调用它们，不同时新写Rust PG/S3 SDK来“绕开”跨语言边界。Rust proxy只做私有协议/值验证与控制，不复制重试/授权/版本规则。
- 双语言common validator是同一wire合同的验证器，不是两套业务；共用schema/golden/rejections。harness、独立truth、fixture writer保留Python，不属于必须迁移的数据库运行时。
- 每一未来Rust迁移单独登记 `module/capability/old authority/new authority/真实consumer/退出条件`；实现前冻结原Python行为和支持矩阵，新旧成对消费同真实PG/S3/Arrow输入，核成功+拒绝+unknown/cancel/版本/计费+固定负载成本。I1真实consumer参与，纯golden对照不足。
- 切换只在可信组合配置选择一个adapter，失败不自动回退legacy/latest。新reader canary通过→切新写/默认读取→旧pin/产物/回滚窗结束→删除旧生产路径；旧实现冻结为参考或只读兼容，不能两边继续独立加功能。PG有持久状态时只一个发布/授权权威，新Rust不得新建平行目录。
- **退出触发点**：I1前不全库重写；I1 scan真实配对之后先评估热点与阻塞数据，再选一个迁移片。任何新增同能力功能只能加到已选权威；双实现验证阶段若下一集成窗仍未达标，ROOT明确回到原权威或重排，不能无限期双轨。硬RSS/不可抢占native预算无法证明时保留missing，逻辑MemoryPool上限不冒称总heap硬限制。

## 5. 四层验证与机器落实

| 层 | 触发/范围 | 必需证明；报告不能混称 |
| --- | --- | --- |
| 模块 M | 该模块生产/测试/driver变更；常规pre-commit和PR默认 | 廉价仓库/DAG/规模/策略恒跑；模块完整适用源strict100%（不是仅changed lines），该语言fmt/lint/test及本模块功能/故障/真实实现性能；可固定fake跨包，但本模块自身PG/S3/Arrow等必须真测。测试only同样运行归属模块测试 |
| 配对 P | 接口、跨模块调用或真实consumer首次接入；模块稳定点后排窗 | 真生产者+消费者+同query/view，边界成功/负例/取消/失败计费/恢复；外部两端都真实，第三方未参与模块可固定fake。保留producer/consumer两套源版本与实际调用证据，不以两个模块各PASS冒充pair |
| 系统 S | ROOT合成可运行旅程、批量集成/主线候选；定时/手工回归 | 当前支持用户路径+所有受影响pair+legacy回归；固定真值/规模/环境，混合预算、更新/撤权/pin/取消与恢复；I1完整仍含SQL/HTTP+精确向量/BM25。扫描先接通可单列内部检查点，不能更名I1完成 |
| 发布 R | release候选 | 全声明能力/模式、完整performance/fault/soak、安全/安装/联合恢复与远端CI；planned/missing仍阻断。不能由模块100%或本机模拟云推出G3/G5 |

选择器必须记录 `level/modules/pairs/requirements/source_closure/denominator/exclusions/commands/reason`。模块覆盖分母为该owner全部生产源，不是只测新文件；未修改依赖可固定版本并明确未认证。公共A/B/C/schema变更选择实际消费者的contract+受影响模块/pair；共享query Compiler变更选query及入口pair；PG schema选catalog+生命周期pair。锁变更按实际依赖扩散，无法确定影响时回退系统层。新增/删除/rename两端、不在owner清单、未映射driver或unknown level都fail closed，不能漏门禁。

机器清单应表达模块命令和pair依赖；原产品timeout/负载不能移成可选。pre-commit→module，pair变更→module+pair，系统组合/关键全局更改→S，R显式。CI继续真实Python支持矩阵；Rust-only不重复全树Python数据库套件，Python-only不重新采集无变Rust全树覆盖。shared contract互通照测。S在集成候选执行一次，不把已匹配源码的M命令再跑三轮当额外质量；报告/receipt应区分本次执行与按完整输入闭包有效的先前证据，不伪造fresh、改base或删除原失败。

## 6. 首批真实配对与最小关键路径

1. **M稳定点**：P00先交模块选择器/报告schema/严格分母，独审后落地；同时P01冻结细化需求矩阵、架构/ROOT确认本表。P03 direct/audit按已审首runner只做26目标+真实functional，保留11新增操作和原0IO负例。P05旧5faf停点独立排R2收尾，不等待其它模块全包。
2. **P03↔P04**：复用已有真实配对实物，在确定源/依赖版本上核批次/fieldID/VersionId/冷暖/失败账；不等待P04 writer/Iceberg/训练。组件历史报告可作有效基线，但新组合的actual calls必须新验。
3. **P02↔P03父控制**：catalog poll/selector接私有父cancel+原mono deadline；对象scope构造接同父起点/剩余额度；授权后fresh wall/mono。现在P03明确只允许内存callback，**真实PG网络callback必须先改合同并真实暂停PG/锁等待/对象故障验整链**；旧socket时限报告不可沿用。PG COMMIT尝试后unknown仍对账。
4. **P04↔Rust query**：一个query的受控私有bridge，P13装配、模块owner提供实现；A canonical(binding/ordinal/ReadBatch)不改。Rust唯一Compiler/Arrow/DF；Python唯一PG/S3/source；bounded frame/背压/序号/binding摘要/单父计量+失败attempt已知性。完整11成员（main10+mirror1）按显式映射保留，不能只取first source或按重复cluster去重；P04单source现范围不足时明确拒绝/补合法映射，不用两个文件冒充两逻辑来源。
5. **P06↔source/storage，再query候选回表**：先冻结最小located-build私有描述符（或A兼容新增kind/能力须P00审批），不猜ReadBatch页号即物理行位；真实artifact字节经P03，query按固定ID/version核回表。I1窄全scan回表可单列限制，不冒称P10按需规模出口；不等ANN/Graph。
6. **正式入口与系统检查点**：P08最小登记/绑定/SQL/HTTP/取消映射到同facade，ROOT组合；先发布可重现的真PG→S3→Parquet→Rust过滤/排序/投影用户结果，再加入BM25/精确向量完成原I1。其后B接入/媒体/更新→I2，C训练实际consumer→I3，均不被首scan替代。

私有bridge首接口清单：可信 `ExecutionControl(T0, deadline, cancel, ledger)` 构造注入；`catalog.bind/reauthorize/release`原A值接口；`source.read_batch(binding,ordinal)`；`artifact.candidates(binding,IndexQuery)`；query typed result含ID/version sidecar。外层帧带版本/长度/序号/query/request/binding摘要，不把secret/授权true当参数。query拥有语义proxy，ROOT组合根装配真实adapters；cluster仅可提供不导入上层的通用进程/传输监督，不以bridge之名反向依赖query/catalog/connectors。先记录attempt再I/O，成功A Usage只核delta不重加；中断缺尾账时known=false+保留上界、不填0。丢Future/spawn_blocking不证明停止；父监督者必须实际kill/wait/reap本query资源，release未知按原lease处理。详细接口需独立复核后实施，当前只是最小需求。

**等待上限（调度目标，非产品SLO）**：SOURCE/模块稳定点交接后ROOT在下一调度轮、最迟30分钟指定reviewer/consumer；真实pair最迟下一可用独占窗口、目标2小时内启动。超过2小时记录阻塞owner/原因/解除动作，超过一个工作日必须拆最小pair或明确重排，不允许静默等待全包。受控性能仍独占，普通无污染模块unit允许并行；不能把所有功能测试也长期串为全库窗口。审查者不可是该实现作者，需临时换角色时先停其writer并交接。

## 7. 独立物理PG块需求与交付数据

PG物理导入沿用[需求矩阵 B01–B05](../product/requirements-v2.md)，分别研究 Lakebase 离线 heap/index slices 经目标 storage-ingest 原子发布，以及 Neon compute/WAL/pageserver 的版本化页协议；二者不互相背书，也不以普通 PG wire 或逻辑 COPY 代替验收。官方证据、精确版本/build、页/索引/TOAST/catalog 兼容与故障恢复见[独立研究和原型合同](../research/2026-10-21-pg-physical-ingest.md)。connectors 负责格式 builder、源捕获、兼容矩阵与目标原生 receipt；storage 负责不可变物理字节及校验。**目标 PG/原生 storage-ingest 协议拥有物理权威、原子提交及其 WAL/页恢复责任**；Gura catalog 只维护自身 intent/revision/read view 的发布与对账，不能代替目标提交。跨目标恢复需双方原生状态与 receipt 对账，query/gateway 只消费已发布结果。目标扩展/API 尚未取得，本机 PG18 原语实验只验证可生成和读回的格式事实，不认证 Lakebase 导入或 Neon 写页。

每功能点至少记需求ID、M/P/S/R状态、真实用户链路、源/合同/报告指纹、Rust行为行/公共合同/测试/工具四类投入、验证耗时/首次通过率、等待pair时长、阻塞及owner；首次失败与fixture成本单列保留。工程优化优先复用固定工具镜像/锁缓存与模块报告闭包、减少全库覆盖/重复环境创建；不得复用profile计数伪fresh或降低测试负载。ROOT整合到正式计划/模块合同后，P00实施机器门禁，由非作者独审与实际before/after命令选择及成本证据确认。
