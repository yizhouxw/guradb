# 实施事实账本

2026-10-21 16:34 UTC 本地组件与真实配对检查点；15:25快照保存在8823331。执行[策略 v2](2026-10-21-modular-delivery-v2.md)，需求见[矩阵](../product/requirements-v2.md)，机器度量见[JSON](2026-10-21-delivery-metrics.json)。14:43 快照保存在前一 commit；本页按新源码/实际命令续记，旧失败原件保留。合同、模块、真实配对与主线用户能力分别验收。

## 已验出口与真实链路

| 功能面 | 实际证据与本轮结果 | 当前出口与缺口 |
| --- | --- | --- |
| CF1-A / 独立真值 | 主线既有12 golden/23拒绝双语互通、P01全11成员；唯一Rust SQL core已合 `1e4f6a6` | 合同/核心实物，不是新 PG→对象→SQL 用户链；人工相关性/业务数据仍缺 |
| P02固定目录 | `86fcaf0`；原4d基点，正常hook/clean post均10suite/29命令，六轮真实PG，独审de26d633；task b826完成、checkpoint125543…b6e71f7f | [PR14](https://github.com/yizhouxw/guradb/pull/14)分支已验；真实PG父控制→读取、CI/main待闭合 |
| P03固定对象读取 | 新44源 `2d1dfa7d`：34纯单元+26socket/存储单元，以及原12功能/4性能/12故障全部实际通过。真实窗口50.131s，ROOT释放5ad7d23c、p01独审0c05f60e | 只读组件稳定，已用于A真实配对；新task476c1的原4d strict/full、正常提交/PR仍待完成。SDK写入诊断原LIST7/预期8 FAIL、旧PR13失败保留，未改期望 |
| P03→P04真实配对 A | 新28源 `51601127`：44单元，真实Seaweed/S3→固定对象→窄Parquet→ReadBatch；原6功能/4性能/23故障通过。3CLI分别17.743/16.660/5.620s；314许可证据/3.319MB，ROOT逐原件复核fdd9a13e | 本地**单SourceVersion组件配对**通过；原receipt4696/base17d的strict/full/提交尚未完成，p01实物独审ef3e107e。不是多Source、真实PG/Rust、主线或I1 |
| P05 Rust固定查询 | 新31源 `c32f44b6`：R2完整Value预约与NULL fixture修复后，首次完整 `cargo test --package guradb-query --lib --locked` 55/55，0过滤/忽略，外16.612s；p01实物独审8e51f46b | 真Arrow/DF及全11行/8192源行32批的lib测试已运行；fixture provider对象IO为0。新M1 strict/真实组件性能/故障、真实Source消费者仍待验，不能借旧M0报告标绿 |
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
| B2：显式located出口 | plan_audit | B1实际main10+mirror1与双源130已独审通过；现实施B2私有located SOURCE，联合封包/费用/定位另验，不重开父账 |
| P05新M1模块出口 | p00 | 最小native probe+独立PyArrow/PG真值计划先冻结输入与父managed-memory预算；新8192/两Parquet/5cold+warm性能和故障、strict按真实实现验，legacy-M0不代验 |
| C：真实PG父控制→读取 | ROOT装配；接口由原模块owner供应 | catalog受控调用与storage/source父控制接入口缺；PG网络reauth不能塞进仅认证内存callback。实际暂停PG/撤权/对象故障须验证同父期限/取消/lease清理 |
| D：真实Source→Rust | ROOT组合；query owner实现消费者 | B+C+P05模块稳定后接有界bridge；禁止以SealedFixture的0对象IO包装真实源。保留全11成员、失败attempt已知性、背压/取消/kill-wait-reap |
| E/F：索引回表与正式入口 | p00负责E；ROOT负责F | E接B/C located及真实跨attempt父账，再由D回表；F正式HTTP/PG只调用同一Rust facade，先S-SCAN再补完整I1 |
| PG物理目标原型 | connectors DRI；p01研究 | 缺目标原生extension/API及版本兼容合同；隔离stock PG原语已验，不阻塞对象湖scan，不伪造物理写入接口 |

A的稳定交接从P03 ROOT释放14:57:38到P04首功能命令15:18:34约20.9分钟；15:20确认资源回基线。这个时间只说明局部模块稳定后尽早配对，不认证全模块/M→S。P02从12:55:43 task-finish至15:25历史快照约149分钟；本16:34快照约218.6分钟仍未main集成，精确分钟见JSON；其中也有接口等待，不能全部归因账户。

四个实际槽位：ROOT负责PM/共享/组合与事实；p01产品及独立测试/文档审查；plan_audit负责storage/connectors；p00负责query/工程工具。当前两个稳定候选交接后，当前两项行为在制为B2与P05 probe修订；旧P03/P06/P08现场保留但未同时派发行为写入。SOURCE-only准备、复核、文档不冒充额外开发并发。

## 验证成本、首次结果和工程优化

P02原完整窗口1404.400s，hook724.422s/post673.946s，六PG driver约80.033s。它与新模块范围不同，不能直接宣称加速比。工具engineering hook/post121.933/114.521s也只认证工程工具。原strict探针192.390s实际Rust710/711失败、三个M0未执行，红项与profiles保留；query补两例后在新精确源码上完成整模块，不改100%或排除。

P03新组件纯34单元4.039s，另26socket+三原driver50.131s；P04复用已核三锁的现有matching venv，不重建环境，44单元0.778s，三driver合计40.023s；P05首次native编译14.85s、test1.49s。组件等待与验证耗时分别计，不以快速lib测试代替新M1性能。此前P03诊断失败29.131s、镜像预检与PG引用解析失败继续单列。

query两轮coverage原件用一次遍历清单/归档，外层各约0.65/0.67s，profile与tar保留；独审明确只流读post native一次，不反复扫描历史bulk。已定位的重复编译与夹具启动/清理成本仍须分段证据，下一工程小片只给原命令加有界阶段/dirty原因观测，不先改cache、规模或阈值。Python模块ready映射需随真实组件及完整owner分母单独交付，不能由现有Rust映射推定。

全历史功能首次通过率仍未知；新query测试小片首完整模块1/1、P05首native/lib阶段1/1、A当前fixed-source候选三driver首轮1/1分别记账，后两者不计完整模块/新用户功能首次通过率。Rust行为、公共合同、测试、工程工具四栏独立统计，不用文件/行数计算产品百分比。本机模拟云只覆盖同一物理故障域；真实三机、云认证、HA/PITR、完整performance/stability/soak与发布仍缺。

下一可观察用户结果仍是主线上可复现的正式S-SCAN，随后完整I1，再图文更新I2及实际训练I3。当前A和55lib是向该结果前进的实际证据，尚不能把用户结果标完成。

## 16:34 UTC 双源配对与工程增量

B1 source30 `0de215b4`：65单元内0.706s/外0.973s；实际功能10/24.032s、性能8/18.914s、故障26/5.884s通过。p01独审e8a78f02核14实际Parquet、52原始ReadBatch/replay、34页与59故障对象；全11来源/值/物理定位、双源130的64/64/2和同父账吻合。最大page38.964ms/cohort58.985ms、取消7.024ms，原cap不变。此为本地组件与P03真实配对，不认证strict/full/PG/Rust/B2/P06/main/I1。

首轮65内0.726s/外1.117s有1个新增oracle错误，三个CLI未启动；窄修只注入确定时钟并加强1ms期限收紧，原44与21定义/生产/预算不变。修后3CLI首次实际执行全通过，外层52.139s仍因索引漏列既有.bin而FAIL。只按26个objects.json补精确59bin/450文件7.040MB索引353223d5、独立释放4b543，未重跑已过组件/未改原FAIL。系统default bridge ID变化原因未证，containers为0/volumes同基线/自有PID均退出，不清理未知资源。

工程PR16已续至`23a2e37`，完整22文件：main-only push去重、2个触发正负例、PR auto/main system/manual/schedule/release保留。normal hook116.937s、own-base post40.996s，5/5且134 harness/136合同/native9；额外整PR范围检查41.042s，非作者独审6a45a55e。native编译行56/0/0只是观测，根因/全局提速未证。PR15前片已结项至8823331；15:54最新PR15/16 run仍0步骤计费失败，未合入，16:10:57 fetch主线1e4。

P05 probe初稿004561f2经ROOT与架构师167176 SOURCE审查：真实query身份不一致、启动前归属证据/unknown清理、T0内部截止需修，尚未新构建/性能运行。p00有限修并加4个launcher负例；256MiB/32MiB只是ROOT事前试验profile，原8192/两Parquet/32批/三列1000/5cold+warm和10s/RSS512MiB不变。plan_audit已承接B2 located源码；当前两个行为WIP、四实际槽位，无性能资源在用。

C架构只读复核7a2c1a53列出真实供应方缺口：PG受控父期限/取消与未知bind未获pin时按原request精确cleanup。查无query不能宣称终局；若阻止未来迟到重建须独立持久合同/配额/迁移，现未实现。全历史功能首次率未知；unit、3组件命令、证据工程分别记0/1、3/3、0/1，不把它们混为新用户功能率。下一正式用户结果仍是主线S-SCAN再I1，当前尚未交付。
