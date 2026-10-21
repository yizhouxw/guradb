# 实施事实账本

2026-10-21 策略修订快照；执行[策略 v2](2026-10-21-modular-delivery-v2.md)，需求见[矩阵](../product/requirements-v2.md)。旧包状态表已由功能点/证据层替代，历史记录可从 Git 和任务 receipt 取回。本页不把 SOURCE、合同或模拟写成用户能力。

## 已验出口与用户链路

| 功能面 | 已有实际证据 / 层级 | 当前出口与未完成项 |
| --- | --- | --- |
| 共同读 CF1-A / 独立真值 | 已合主线：12 golden/23拒绝双语真实互通；P01 synthetic全11成员；PR9/7历史main已闭合 | 合同互通；不是PG→对象→SQL用户链；人工相关性/业务样本缺失 |
| 唯一 SQL core 提取 | PR11精确main `1e4f6a6`，本地报告 `bc049da2…`、两版本PR/main CI已有对应历史证据 | Rust行为结构复用；固定查询执行/正式新入口未接通 |
| P02固定目录 | `86fcaf0`，原base `4d6baca`；正常hook及clean post均10suite/29命令；post `5b3f0f1f…`，六轮真实PG、七容量/unknown/暂停COMMIT独审 `de26d633…`；task b826完成，checkpoint `125543…b6e71f7f`，已正常推送 | 模块/分支已验；[PR14](https://github.com/yizhouxw/guradb/pull/14)已核无重复后通过现有认证标准API创建；远端CI/main未闭合 |
| P03固定对象 | 新42源 a828完成源码独审；旧PR13双CI真实InternalError500失败保留 | 新组件首窗仅只读镜像预检失败：实际默认为固定index bb05/arm64，旧runner要求5a93/amd64；0安装/0测试/0服务，源码不变、实际0容器后已释放。修共享环境适配，不反复整仓 |
| P04固定源 | 历史真实S3/Parquet三组件和Python270/4474覆盖有精确旧源码证据 | 新主线/真正Rust消费者未验；当前1000行/4文件/16rowgroup边界，不承接10k后续profile |
| P05固定查询 | A1a26目标单元与Rust严格覆盖有精确历史证据；新M1实现与独审发现R2保存 | 当前a925 PARTIAL稳定停点；完整Value预约修订/新单位/编译未完，不将原A1a覆盖挪作M1绿；P00工具交付后继续 |
| P06固定索引 | 历史真实产物与独立BM25/L2数学证据 | 当前100行/单shard/1MiB，真实Source→Index→Query回表未通，ANN/Graph另需求 |
| 真实用户纵向闭环 | **新共同I1/I2/I3均未通过**；现有legacy alpha入口保持其原有边界 | 下一个用户结果为S-SCAN；不得用组件证据或新文档提升I1 |
| PG物理直写 | 官方路径/版本事实已核：Lakebase物理页bulk、Neon WAL/page、普通逻辑COPY分别立需求；PG18.6/aarch64原语34命令/3.714s、12行读回与三个SQLSTATE实际通过，ROOT独审049cbb98 | 只证明格式原语；目标原生extension/API/物理兼容与恢复仍missing；不将wire/COPY绿冒充物理ingest |

截至本轮12:55 UTC实际fetch，origin/main为 `1e4f6a6c26eb28982f4b61cc75aa05e290211809`。后续远端状态须重新查询；此快照不声称未再推进。机器分层实现位于独立 `gates-v2` 任务：20文件SOURCE候选e0aff5，原三项独审阻断已有作者窄修，整体增审/真实运行待验，不能宣称已生效。

## 关键路径、阻塞和负责人

| 事项 | 唯一负责人 | blocked/等待起点与解除动作 |
| --- | --- | --- |
| 分层门禁与防伪 | p00实现 / plan_audit独审 / ROOT集成 | 13:01 UTC任务972583启动；修planned遗漏、完整分母和logic指纹，132项harness/136项合同及仓库/策略实际bootstrap通过（50.765s），新scoped覆盖/代表性真组件及normalhook/post仍待验后接入 |
| 策略/需求/模块合同 | ROOT / 产品与架构交叉审 | 13:01任务96cfa启动；42条唯一owner，独审五项容量/绑定/TTL/集合修订已落实，待最终复核/分支交付 |
| P02远端PR/CI | ROOT | 12:56 UTC连接器429保留；13:45核无重复并创建PR14，分支86fc；解除创建阻塞，双CI待实核；不等待它才做模块源码/本机验证 |
| P03环境夹具 | plan_audit接权后 / ROOT排窗 | 本轮readonly预检停止；用实际backend/platform与固定索引记录、消除过期ID假设，再仅模块验证 |
| P05结果内存预约 | p00工具交接后 | a925部分修订已保留；新增边界单位/独审/真实Arrow-DF模块验收，不等P03整个包 |
| 真实配对与正式入口 | ROOT / 两端owner / p01独立真值 | P-OBJECT-SOURCE、P-CONTROL-READ、P-SOURCE-QUERY按稳定面排窗；当前未记录pair通过时间，等待量不能手填0 |
| PG物理原生目标 | connectors DRI / p01研究 | 官方未提供本轮可运行的目标extension/API；PG18隔离格式原语已实测；目标ingest仍missing，不用普通COPY替代 |

本机模拟云为用户授权环境；外部付费资源/远端设置/真实云部署未授权。多容器共享物理故障域，真实云、独立三机、PGHA/PITR和生产认证分别缺证据。

## 耗时、首次结果与投入分类

P02最终一次受控窗口外层1404.400s：正常commit/hook724.422s、clean post673.946s；其中六个真实PG driver合计约80.033s。这些是同次已记录耗时，不能把差值全部归咎于无用测试，也不作为产品吞吐基线。新分层bootstrap实测50.765s，仅4条廉价命令/132项工具测试和136项合同测试；不能与P02完整质量窗口作同负载加速比较。可比模块after保持null，须同输入/能力/预算测量。

P03新窗是环境预检失败，未进入质量执行；保留失败分类/实际镜像身份，不能记“单元0项通过”。P05有原库编译/fixture及内存审查问题，旧完整首失败时间序列未统一入账；目前不公布伪精确总首次通过率。新任务从首次完整计划执行起记分子/分母，环境预检另外统计，未执行为null；定义见策略v2。

投入分为四栏：Rust行为（已提取core、M1待验）；公共合同（CF1-A及v2需求/边界）；测试（独立truth/组件/PG物理原型）；工程工具（harness/CI/夹具/缓存/归档）。各栏不互换成功数，不以文件/行数计算产品完成百分比。机器可读的当前已记录时间与缺口见[度量快照](2026-10-21-delivery-metrics.json)。

## 下一可观察结果

1. 新门禁真实选择query/storage模块路径，原system/release义务及必要planned缺失仍失败；报告不可篡改层级/分母/算法/基点。
2. P03模块仅跑本次受影响单元及真实S3功能/成本/故障，P05独立完成Arrow/DF模块；稳定即配对。
3. main上的S-SCAN可从正式入口得到固定view、完整稳定ID/version及SQL过滤排序结果；再接检索完成原I1。每个阶段实测后更新本页，不提前标完成。
