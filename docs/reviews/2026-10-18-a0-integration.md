# A0 集成复核：能力合同、证据保全与独立真值

日期：2026-10-18。主线起点 `d95d1ada607fe40a6b1cf8eb19773b3a10f95bae`，工作区干净。
范围：[下一阶段计划A0](../plans/2026-10-18-next-stage.md)，不实施A1–A6。
切片验收已完成；最终主线验收严格绑定 `a0-main-integration` receipt 中的commit、报告和checkpoint，不能用下列分支报告代替。执行合同见[集成计划](../design/a0-main-integration-change-plan.md)。

## 完成内容与证据

| 切片 | 交付与边界 | 提交及切片最终报告 |
| --- | --- | --- |
| 支持矩阵 | [离线清单v1](../../api/capabilities/v1.json)及schema覆盖12域；两个OpenAPI引用同一合同；M0/M1M2、BM25 v1/v2、源append/索引全重建、内部Lance/外部连接器分开 | `cf5b4838a941ccb636fb26c15fc5566490bb9b1e`；`20261018T105752Z-0694a385`，7 suites/20 commands |
| M0证据 | result/trace/build/容器日志接入v2归档；新运行强制身份与逐日志摘要，停止→采集→删除，失败保留现场 | `f58e69050faf6fa6ffc5fc635dbab33d552854d9`；`20261018T110340Z-d1e26c7b`，8 suites/23 commands |
| 独立真值及负载 | [synthetic合同](../design/a0-workload-contract.md)冻结源行/向量/查询；独立BM25、穷举L2、RRF、训练manifest；定时8次更新覆盖四个窗口段 | `063ef1ec48674e452f1faa18a397c7a31e883572`；`20261018T105731Z-6846552d`，4 suites及独立local/HTTP60 |
| 摘要修复 | 持久向量ID使用字符串键；JSON读取后重算dataset/query/workload摘要，实际数据/查询/预算不变，旧归档不重写 | `abc33bcd5211ecb6f7b9316e4b1087e9d8c8bb25`；`20261018T111205Z-8c59c03a`，4 suites及新commit local/HTTP60 |

报告在各保留worktree的 `artifacts/harness/<run>/report.json`，task-finish已将报告及命令日志复制到共同Git目录 `guradb/evidence/`。原始测量另在 `guradb/{m0,p0}-evidence/v2/<manifest-sha>/`，每个manifest逐文件绑定SHA-256；本地归档不是异地备份或不可篡改存储。

能力清单是**源码版本的离线合同**，不表示运行中的部署具有全局能力协商接口。dataset describe仍只公开schema/model/read_context/retention。HTTP/CLI/MCP生产接口没有增加样本过滤、投影或公开写入。

P0原六类查询保留并增加过滤/NULL用例。60秒输入从256增长至384行、9个源批次、10个目录run（含图），每个四分位都要求至少一次读取、append和publish；计划时点与修复分支实测每段均为两次更新。未改变32批/10000行/128 run保护。P0真值来自写入前输入，受理handle与响应绑定同一view；未独立认证默认最新view在受理时的选择时刻。

## 历史保全与修复发现

旧M0证据来自 `artifacts/harness/20261018T054547Z-0d10c08b/`，绑定 `4de2fde7faf04b640ae8dbe02022e78e94db59ee`、checkout digest `147a1624fae4b814878d797ea84f2ec3712313cf157c4ea3191c2540334daf3e`。从原harness归档命令日志核对result，再核对trace及Cargo.lock；复制前后源字节/mtime一致，保留原artifacts。

| 原始套件 | v2原始归档摘要 |
| --- | --- |
| functional | `71ff0fb7fb1d7e56f9e8f19a33bfc81fb2a9a161645f620e0f2456310d616a06` |
| performance-smoke | `ea196ef099d96d2e23f3dbf398ec7b22d3b3ce87c35ef3cb32990cdbdab304fe` |
| stability-component | `6f03b55ed72ba946aff65d607fe38398c7e1c58afba01b8c6a214a30037d5a64` |

历史21份容器日志中14份只有Docker容器不存在错误（functional8、performance4、stability2）：旧重启路径先删除容器，结束时才采日志。**这些日志无法恢复**，其原始字节没有更早的独立摘要锚点；保存现存文件不等于证明历史日志完整。新协议逐容器记录成功采集和哈希，停止失败须确认容器已停，否则保留现场并失败。

独立集成复核还发现旧P0 `dataset_digest` 在内存整数键和JSON字符串键之间排序不同；新增local/timed往返负例先失败，修复后通过。旧 `063ef1e` 证据只保留其原有意义，不补写摘要。修复commit的新HTTP60归档 `69c03857270ed5a02b18569034def6e74bcfd8b714cb9e211caf657ed7819f38` 已核验全部9个文件、9个view、260个响应及三类摘要，四段append/publish均为2；它仍只是本地synthetic组件证据。

通用v2归档以完整内容形成身份，同result而不同trace/log形成不同归档；M0新协议对result中已绑定的trace/log摘要不匹配直接拒绝。两者不能混写为“接受损坏证据”。重复、缺件、损坏、并发、日志失败和JSON往返均有负例。

## 主线验收与后续进入条件

共享 `m0lib/kit.py` 还属于P0 driver摘要；合并后必须重测，分支证据不能证明组合代码。主线按原始基点执行完整plan所选8 suites，包括Rust、M0/M1/M2、local/HTTP P0、60秒窗口、恢复/检查/rebuild和组件故障。所有重型命令及hook持同一fcntl锁串行运行；最终报告和原始归档须匹配最终commit/checkout。独立复核及精确报告路径归入task receipt，未通过不得task-finish。

本片没有获准业务数据；媒体负载0对象/字节。OS缓存未受控，真冷/热/部分命中/超过缓存未运行；本地源不能提供远端S3 GET/HEAD，训练协调器I/O、native完整峰值RSS及五次受控重复仍缺。训练独立真值验证manifest样本/model/media，未独立读取实际Parquet逐值比对。60秒更新负载是新版本，不能与旧两次append结果比较后声称提速。

- A1：以全视图身份/version/split作基线，补独立PyArrow Parquet真值，再实现受限过滤/投影和NULL/int8、撤权/取消/pin负例。
- A2：先冻结版本化描述符、不可变对象哈希及缓存/pin/GC语义，在同输入同质量下计总RSS和真实I/O；取得证据后才讨论放宽规模。
- A3：先设计history/operation保留、tombstone和未知提交对账，再用合法负载跨128 run；32批/10000行保持明确拒绝。

完整performance/stability/soak仍planned；完整M2、跨机M3、生产发布及新远端CI均未验收。主线本地闭环不授权推送或部署。
