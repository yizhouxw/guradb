# 实施事实账本

2026-10-21 14:43 UTC 首批交付快照；执行[策略 v2](2026-10-21-modular-delivery-v2.md)，需求见[矩阵](../product/requirements-v2.md)。旧包状态表已由功能点/证据层替代，历史记录可从 Git 和任务 receipt 取回。本页不把 SOURCE、合同或模拟写成用户能力。

## 已验出口与用户链路

| 功能面 | 已有实际证据 / 层级 | 当前出口与未完成项 |
| --- | --- | --- |
| 共同读 CF1-A / 独立真值 | 已合主线：12 golden/23拒绝双语真实互通；P01 synthetic全11成员；PR9/7历史main已闭合 | 合同互通；不是PG→对象→SQL用户链；人工相关性/业务样本缺失 |
| 唯一 SQL core 提取 | PR11精确main `1e4f6a6`，本地报告 `bc049da2…`、两版本PR/main CI已有对应历史证据 | Rust行为结构复用；固定查询执行/正式新入口未接通 |
| P02固定目录 | `86fcaf0`，原base `4d6baca`；正常hook及clean post均10suite/29命令；post `5b3f0f1f…`，六轮真实PG、七容量/unknown/暂停COMMIT独审 `de26d633…`；task b826完成，checkpoint `125543…b6e71f7f`，已正常推送 | 模块/分支已验；[PR14](https://github.com/yizhouxw/guradb/pull/14)已核无重复后通过现有认证标准API创建；远端CI/main未闭合 |
| P03固定对象 | 42 源 a828 原样保留；校正镜像身份后 26 单元通过，functional 在 dot 前 LIST 实际 7/预期 8 而失败，缺 repeated-separator；该 key 的固定 GET 此前成功；旧 PR13 的 500 失败也保留 | dot PUT/健康 GET 本次未执行。非作者边界审查 82913fed 同意 docs-first 分离只读产品验收与 SDK 写入诊断；新目录 task476c1 保留原 4d base/42 源，旧 task1bea 已交接停止，原诊断不改期望、不标通过；新 44 源独审 b448c266 与 ROOT 05d4a89c 已通过；新运行仍待验 |
| P04固定源 | 历史真实S3/Parquet三组件和Python270/4474覆盖有精确旧源码证据 | 新主线/真正Rust消费者未验；当前1000行/4文件/16rowgroup边界，不承接10k后续profile |
| P05固定查询 | A1a26目标单元与Rust严格覆盖有精确历史证据；新M1实现与独审发现R2保存 | 当前a925 PARTIAL稳定停点；完整Value预约修订/新单位/编译未完，不将原A1a覆盖挪作M1绿；P00工具交付后继续 |
| P06固定索引 | 历史真实产物与独立BM25/L2数学证据 | 当前100行/单shard/1MiB，真实Source→Index→Query回表未通，ANN/Graph另需求 |
| 真实用户纵向闭环 | **新共同I1/I2/I3均未通过**；现有legacy alpha入口保持其原有边界 | 下一个用户结果为S-SCAN；不得用组件证据或新文档提升I1 |
| PG物理直写 | 官方路径/版本事实已核：Lakebase物理页bulk、Neon WAL/page、普通逻辑COPY分别立需求；PG18.6/aarch64原语34命令/3.714s、12行读回与三个SQLSTATE实际通过，ROOT独审049cbb98 | 只证明格式原语；目标原生extension/API/物理兼容与恢复仍missing；不将wire/COPY绿冒充物理ingest |
| 策略与需求 | 19 文档、42 需求，产品/架构非作者交叉审查；`0981fc3` 正常 hook/clean post 各 4/4，post fe87d072，task96cfa 已结项，[PR15](https://github.com/yizhouxw/guradb/pull/15) 已推送 | 本轮只更新实际交付与配对缺口；文档不是新增数据库行为，PR 尚未合主线 |
| 分层门禁工具 | 21 文件 `82b2bfe`，正常 hook/clean post 各 engineering 5/5；每轮 132 harness、136 合同及 query-lib 9 项测试，独审和 ROOT 双报告核验 21d91c1d；task972583 已结项，[PR16](https://github.com/yizhouxw/guradb/pull/16) 已推送 | 初始只映射 Rust query/storage 和 legacy-M0；一次 strict 探针实测 Python976/976、Rust710/711 而 FAIL，三个 M0 未执行。原 profile 及红项独审 c53194cf 保留；可执行映射不等于模块认证 |
| query 本模块补测 | task7c822 以 `82b2bfe` 固定为依赖；原 5 例完整保留，新增两例公共 Describe 数值推断/类型冲突/溢出；SOURCE 非作者复核通过 | 正常提交 hook 首次完整 module 9/9 suite、11/11 命令通过，报告07df4eae，提交 `ad5c9fe`；完整12源，Rust618/618适用行、原owner排除5，三个真实M0全通过，ROOT逐11日志SHA/退出码核实。clean原base post尚待完成；不是P05/CF1-A/I1 |

最近本地 fetch 为 14:19 UTC，origin/main 为 `1e4f6a6c26eb28982f4b61cc75aa05e290211809`；14:33 UTC REST 核对 PR14/15/16 的 base/head 与 open 状态一致，未合入。三份 PR 的两个 quality 作业均因账户付款/支出额度问题未启动（`steps=[]`），没有任何 CI 测试结果。ROOT 已告知用户处理账户；不改账户、门禁或合入条件，继续本地模块工作。远端后续推进仍须重新查询。

## 关键路径、阻塞和负责人

| 事项 | 唯一负责人 | blocked/等待起点与解除动作 |
| --- | --- | --- |
| 分层门禁与防伪 | p00实现 / plan_audit独审 / ROOT集成 | 工具分支已验，PR16 等账户解锁后 CI/main；query 新 task 补唯一覆盖缺口，禁止降低 100% 或减少原三个 M0 |
| 策略/需求/模块合同 | ROOT / 产品与架构交叉审 | PR15 分支已验；本轮 task5e78 记录新事实及真实接口缺口，最后核完整 PR 原 1e4 范围 |
| PR14/15/16 远端 CI | 用户处理账户 / ROOT 集成 | 13:46 起实际付款/额度阻止作业启动；14:33 核三 PR 同因。PR14 的模块从 12:55:43 task-finish 起至 14:43:44 已待集成 108.0 分钟；等待真实配对也受 P03/P04 接口稳定性约束，不能全归因 CI |
| P03产品/夹具边界 | plan_audit实现 / p01与ROOT独审 | 原 functional FAIL 保留；14:31 在新目录 recover/task476c1，原 base 不缩短。先分离诊断并复核完整读取验收，再一次实际验证；不反复换镜像 ID 或降低 LIST 期望 |
| P05结果内存预约 | p00工具交接后 | a925部分修订已保留；新增边界单位/独审/真实Arrow-DF模块验收，不等P03整个包 |
| 真实配对与正式入口 | ROOT / 两端owner / p01独立真值 | P-OBJECT-SOURCE、P-CONTROL-READ、P-SOURCE-QUERY按稳定面排窗；当前未记录pair通过时间，等待量不能手填0 |
| PG物理原生目标 | connectors DRI / p01研究 | 官方未提供本轮可运行的目标extension/API；PG18隔离格式原语已实测；目标ingest仍missing，不用普通COPY替代 |

本机模拟云为用户授权环境；外部付费资源/远端设置/真实云部署未授权。多容器共享物理故障域，真实云、独立三机、PGHA/PITR和生产认证分别缺证据。

## 耗时、首次结果与投入分类

P02最终一次受控窗口外层1404.400s：正常commit/hook724.422s、clean post673.946s；其中六个真实PG driver合计约80.033s。这些是同次已记录耗时，不能把差值全部归咎于无用测试，也不作为产品吞吐基线。新分层bootstrap实测50.765s，仅4条廉价命令/132项工具测试和136项合同测试；不能与P02完整质量窗口作同负载加速比较。可比模块after保持null，须同输入/能力/预算测量。

工具 engineering 完整 hook/post 分别 121.933s/114.521s，通过各 5 suite；此前 strict 探针 192.390s，失败后未运行三个 M0。P03 第二窗外层 29.131s：26 单元通过、functional 23.755s 失败；这是明确的组件失败，不是第一次全模块完成。两次环境预检失败另记，不与源码失败混算。

P05 的旧完整首失败时间序列未统一入账；目前不公布伪精确总首次通过率。新 query 补测片首次完整模块 hook 557.170s 通过，clean post 待完成；这只计测试/验证小片的首次结果，不增加已交用户功能数。Rust阶段 clippy31.874s/test74.377s、coverage188.799s，三个M0外层81.932s/64.058s/66.977s；重复构建/夹具耗时正在单独只读定位。工程工具的首完整成功同样单列，不折算成功能点。耗时来自实际外层/命令日志，归档与缓存成本仍须单独定位，不能凭时间差宣布产品提速。

投入分为四栏：Rust行为（已提取core、M1待验）；公共合同（CF1-A及v2需求/边界）；测试（独立truth/组件/PG物理原型）；工程工具（harness/CI/夹具/缓存/归档）。各栏不互换成功数，不以文件/行数计算产品完成百分比。机器可读的当前已记录时间与缺口见[度量快照](2026-10-21-delivery-metrics.json)。

## 下一可观察结果

1. 新门禁真实选择query/storage模块路径，原system/release义务及必要planned缺失仍失败；报告不可篡改层级/分母/算法/基点。
2. P03模块仅跑本次受影响单元及真实S3功能/成本/故障，P05独立完成Arrow/DF模块；稳定即配对。
3. main上的S-SCAN可从正式入口得到固定view、完整稳定ID/version及SQL过滤排序结果；再接检索完成原I1。每个阶段实测后更新本页，不提前标完成。
