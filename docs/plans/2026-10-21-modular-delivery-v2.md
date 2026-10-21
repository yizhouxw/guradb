# 实施策略 v2：模块交付与连续配对

2026-10-21。执行决定见 [ADR0022](../decisions/0022-module-delivery-and-validation-levels.md)。本页替代旧并行计划中的任务粒度、排程与日常门禁安排；P00–P20、I1–I3、G1–G5 的产品验收义务保留。需求以[功能矩阵](../product/requirements-v2.md)为准，模块职责与运行时权威以[模块交付合同](../design/module-delivery-contracts.md)为准。

## 当前交付目标

先使用户在主线重复得到：登记已保护固定输入 → 真实 PG 绑定 → 固定对象与 Parquet → Rust 过滤/排序/投影 → HTTP 与 PG 返回相同 ID/version。扫描链先形成可运行小片，再接 BM25/精确向量完成 I1；随后图文实际取字节与更新完成 I2，实际训练框架消费完成 I3。每个系统检查点保存教程、独立真值、负例、精确 main commit 与复现命令。

工作单位改为“需求 ID + 可消费接口 + 可验证出口”，不等待整个 P 包完成。边界经架构与消费者必要复核即实现；模块稳定即约真实配对，配对中发现的接口问题回到唯一 owner 修订。完整合同、模拟互通、模块实测、真实配对和用户系统结果分别记账。

## 四个有效槽位

| 槽位 / 具名负责人 | 当前任务及唯一文件域 | 下一职责 / 独立审查 |
| --- | --- | --- |
| ROOT：项目经理、集成与文档 | `codex/strategy-v2` 两片已结项至 `6a56e54`、[PR15](https://github.com/yizhouxw/guradb/pull/15)；本轮 task `a333a15a124b498da3774a1c8fe64b2e` 仅更新计划/事实/度量；协调共享写权 | 维护关键路径、接受交接、排资源与批次、消除阻塞；入口/组合根实现；不自批自己的实现 |
| p01_oracles：产品经理、测试 | 需求粒度/正负验收、独立真值、物理 PG 官方研究及有界原型；当前只在其独占 ignored 目录准备，tracked 由 ROOT 整合 | 独审架构/用户合同，随后承担真实配对与用户系统验证；自己写的 oracle/原型由 ROOT 或架构师审 |
| plan_audit：架构师、模块开发 | P03 只读组件已验；`codex/p04-fixed-source-p03` task `4696bbe16be041d3b900019fe2fd08b3` 的原真实对象→源配对已重新实测；现在只准备 B 多来源最小切片 | storage/connectors 单一 writer；其实现由 p01 与 ROOT 审。P03/P04 原 receipt 的 strict/full/提交出口尚未完成，不并开两套行为修改 |
| p00_cf1a：模块开发、工程工具 | 工具 PR16 与 query 补测 task7c822 已结项，补测 [Draft PR17](https://github.com/yizhouxw/guradb/pull/17) 依赖 PR16；当前 P05 task `bc81c2ae8eb94fb99a646c061a61c35c` 首次完整 Rust lib 55 项已验 | 下一片为新 M1 真实组件性能/故障与 strict，先冻结最小 probe 及预算；随后提供真实 Source 消费接口。common/catalog/index 按稳定点顺序接权 |

同时最多两项行为实现，保留审查能力；角色数不等于并发数。普通无污染单元、源码审查和隔离功能夹具可并行；性能测量独占同一物理资源，coverage 互斥其 target/profile，迁移/组合根有唯一窗口。端口、网络、对象前缀和数据目录必须各自隔离，不把所有测试长期串成整库窗口。

## 首批任务与集成检查点

| ID / 出口 | 唯一负责人；验收与依赖 | 下一消费者 / 阻塞解除动作 |
| --- | --- | --- |
| V2-GATES | p00；`82b2bfe` 工具分支正常 hook/原 base post 各 5/5，非作者独审完成，PR16 待 CI/main | 初始只映射 Rust query/storage 与 legacy-M0；无映射扩大范围。代表性 strict 曾实测 710/711 而失败，不能标模块通过 |
| V2-PRODUCT | ROOT；42 条需求、唯一 owner、预算/错误与版本研究已交 PR15，非作者产品/架构审查及两轮文档检查完成 | 每个开发 DRI；未冻参数/预算的具体需求先交冻结小片，其他已闭合小片继续 |
| M-CATALOG | ROOT 闭合已验 P02 分支：`86fcaf0`，真实 PG 六轮证据已独审、task-finish/正常推送已完成；[PR14](https://github.com/yizhouxw/guradb/pull/14)已创建，双 CI/main 待闭合 | PG 父期限与对象授权配对；连接器 HTTP429仍保留；ROOT已用现有认证的标准API解除PR创建阻塞，继续跟踪CI，不阻止本地模块 |
| M-STORAGE | plan_audit；原诊断 FAIL 保留。新 source44 `2d1dfa7d` 已通过 60 项单元及原只读功能12/性能4/故障12，ROOT与p01独立核原件；原 4d receipt 的 strict/full/提交仍待完成 | 已解除 P04 配对等待；全部合法 special key 固定 GET、0IO dot 拒绝、预算/费用均保留；SDK 写入诊断仍不改 8 为 7、不标绿 |
| M-QUERY | p00；Describe 补测 `ad5c9fe` 的正常 hook/clean post 均 9 suite/11 命令、完整12生产源 strict 与原三个 M0 已验，task7c822 已结项。P05 新 source31 `c32f44b6` 首次完整 lib 55/55，经 p01 非作者实物复核 | P05 新 M1 的 strict/组件性能/故障仍待验，真实 Source 消费接口仍缺；保留全11成员/8192原负载，不以旧M0证据代验新M1 |
| P-OBJECT-SOURCE | plan_audit 实现、p01与ROOT独审：新 source28 `51601127` 的 44单元、原6功能/4性能/23故障实际通过，真实 P03→P04 单 SourceVersion 读取；资源已释放 | A 本地配对稳定点；不是完整多来源 B、整项 strict、PG/Rust、主线或 I1。下一消费者先实现完整两来源及 located 出口 |
| P-CONTROL-READ | ROOT 装配、catalog/storage owner 修各自实现：真实 PG 绑定/reauth→对象，同父 deadline/cancel/ledger | Source/Rust；真实暂停 PG、对象故障与撤权；同步 trait 或内存 callback 不能充当网络期限认证 |
| P-SOURCE-QUERY | ROOT 组合、两端 owner 实现：有界私有 bridge，Python 真源→Rust 唯一 SQL/Arrow/DF，完整两来源 11 成员/稳定 ID | 正式 HTTP/PG；限定 IPC/错误费用/取消与 reap 证明先复核，不另建 Python SQL 引擎 |
| S-SCAN / I1 | ROOT 批次集成，p01 独立用户旅程：先 PG→S3→Parquet→Rust 扫描端到端，再接 P06 候选/回表/正式入口完成原 I1 | I2→I3；扫描成功单列，不把它改称完整 I1 |
| R-PG-PHYSICAL | p01 研究/原型，connectors DRI 接后续实现；[独立物理路径需求](../research/2026-10-21-pg-physical-ingest.md) | 目标版本/扩展/API/一致性/恢复规格；不阻塞对象湖 I1，也不拿 wire/COPY 成功替代物理导入 |

稳定点在下一调度轮、目标 30 分钟内指定 reviewer 和消费者；真实配对在下一可用资源窗口、目标 2 小时内启动。超时记录 `blocked_since/owner/reason/next_action`，超过一个工作日必须拆片或明确重排。这些是调度目标，不是数据库 SLO。ROOT 每轮主动处理等待，不让已稳定模块因未完成的大包长期空置。

首轮实物接口核查后，将上述配对拆为以下可交接小片。p01 负责独立真值与验收；每行只有一个主实现 DRI，供应方接口仍由原模块 owner 修改，ROOT 不在组合根另写模块语义。

| 小片 / DRI | 固定输入 → 验收出口 | 开工依赖与已查明缺口 |
| --- | --- | --- |
| A / plan_audit | P03 真固定 metadata/Parquet → P04 单 source 真 ReadBatch；逐 cell/ID/version/费用及坏 footer/撤权/取消 | P03 读取稳定即可启动；构造接口现可相接，不等 PG/Rust/index；通过只记单 source pair |
| B / plan_audit | 同一完整 revision 的 main10+mirror1 → 全 11 成员与显式 located 描述符、同父账 | A；P04 仍限制一个 source，locations 只有私有状态。不得拆子 view、猜 ordinal 或省 mirror；保留 1000 行/4 文件/16 rowgroup cap |
| C / ROOT | P02 真 PG bind/reauthorize/release → B 原期限/取消/授权与精确 lease 清理 | catalog owner 先交受控调用接口，storage/source owner 交父控制接入口；现网络 reauthorize 不能直接塞入仅认证内存 callback，真实 PG 暂停/撤权须验 |
| D / ROOT | B 全 11 批流+C 父控制 → P05 唯一 Rust Compiler/Arrow/DF 值、身份血缘和真实账 | P05 R2 稳定后 query owner 先交真实 provider 消费者，ROOT 再写有界私有 bridge；现 `execute_fixture(SealedFixture)` 的 0 对象 I/O 账不能包装真源冒充配对；IPC 取消/回收/错尾输入须验 |
| E / p00 | B located+批流 → 真 BM25/exact 产物；P03 读产物→候选；D 真回表 | B+C；现索引 manifest 仍单 source_version_id，独立 ExecutionScope 仅预计一次/size，须显式迁移并接真实跨 attempt 父账。构建可先于 D，回表完成须 D；保留 100 行/单 shard/1MiB |
| F / ROOT | 可信 principal+view+SQL/typed params → 同一 D/E facade 的正式 HTTP/PG | C+D；P08 只有设计，需真正实现入口、bind 一次/portal 固定、完整 fingerprint、失败账和精确 pin 清理。先正式 scan 检查点，再接 E 完成原 I1 |

顺序为 P03 M→A→B，P05 R2 可与 A 独立；C 供应方接口可先准备，真实 PG→读取需稳定 A/B；D 需 B+C+P05，E 构建/产物读可在 B/C 后、候选回表需 D，F 先接 D。完整 11 成员在既有 cap 内，但不推出 8192/10k 整链支持；P05 原 8192/32 batch 验收另保留。子期限取父更小者，不能将 P04 页/查询、P06 build/query 和宿主预算相加或重开 TTL。各 M/P/S 结果分别记录，A 通过不省 B–F。

本轮已实际启动 A：从 P03 只读组件 ROOT 确认稳定点 14:57:38 到 P04 首个真实功能命令 15:18:34 约 20.9 分钟，15:20 已清理并释放。该记录只计算这次局部交接等待，不把两端历史模块各绿当配对，也不把 A 内单 SourceVersion 的11行当 B 的 main10+mirror1 两来源。B 与 P05 模块验收成为下一两项行为工作；ROOT 先冻结它们各自最小接口/预算，再排真实 C/D。

## 四层验证和 CI

| 层 | 触发与范围 | 完成含义 |
| --- | --- | --- |
| module | 普通模块变更；该 owner 全部适用生产源码、语言检查、功能/负例/故障/真实性能及自身真实 PG/S3/Arrow 等依赖 | 跨模块依赖可用固定版本契约/fixture；完整模块适用行严格 100%，不缩成 changed lines；不能宣称配对或系统通过 |
| pair | 两端真实实现消费固定接口，模块稳定点或接口变化 | 核同 view/ID/version、错误/权限/取消/剩余费用及恢复；第三方未参与模块可固定替身 |
| system | 稳定小片组成集成批次、公共入口/全局风险及 main 候选 | 当前支持旅程、受影响配对及 legacy 回归；在集成窗口运行，按整个批次基点验收 |
| release | 声明部署的发布候选 | 完整 performance/stability/soak、安全、安装、升级与联合恢复；planned/missing 继续阻断 |

机器实现由 `gates-v2` 任务提供 `--level auto/module/pair/system/release`、明确 module/pair registry 和 v2 证据绑定；**此策略页本身不证明代码已生效**。pre-commit/PR 自动选实际范围；main/system 与手工 release 分开。未知 owner、未认证映射、公共合同或无法证明影响范围的变更扩大检查；显式要求过窄范围要拒绝。报告和 receipt 固定 level、模块、源闭包、命令/预算、profile 摘要与原始任务基点，模块报告不能冒充 system/release。

15:17 UTC 在各最新 head 核对：PR14/15/16/17 的 8 个两版本 Actions 作业均因账户付款/支出额度未启动，执行步骤为 0。没有 CI 通过证据；ROOT 已请求用户处理账户，保持合入条件，继续本地模块/配对。15:18 fetch 的 main 仍为 `1e4f6a6`；工具在 PR16 分支已实现和验证，主线尚未生效。合入按依赖排 PR15/16、PR17（依赖16），P02与后续读取切片按各自原始范围集成；不跳过远端和合并后系统验证。

工程工具变更运行完整 harness 自测、选择器差异、真实 CLI/报告伪造负例及代表性模块路径；不凭空把所有工具源码加入生产覆盖分母。已有生产严格覆盖、原始性能负载/时限、Rust 有限排除和发布义务保持。门禁调整须非作者审查并给 before/after 实际选择与运行耗时；缺失映射公开列出，不把“有 registry”当已优化所有模块。

第一批保持 main 候选 system 验证，ROOT 将稳定小片聚成集成批次，减少候选次数。未经正式证据复用协议，不跨 commit 拼接旧绿色报告或 profile；先通过范围缩小、明确资源归属和锁定依赖缓存减少重复。任何复用优化都必须验证完整输入闭包、选择器/预算版本及来源，明确引用旧执行，不能伪造 fresh。

## 用结果与阻塞校准速度

每个需求分别记录 M/P/S/R 状态与精确证据；未运行记 pending，已失败保留失败及原因。报告至少给：已验功能点、真实用户链路、关键路径剩余项、阻塞 owner/起点/解除条件、等待集成分钟、验证命令耗时及首次通过率。

首次通过率 = 首次完整计划执行即通过的功能点数 / 已有首次完整执行的功能点数；环境预检、实现、oracle、门禁与证据失败分别分类，未执行不计分母。不使用最终绿次数作分子；逐重试成本保留。Rust 行为、公共合同、测试、工具分别统计变更，不把合同/工具行数算用户功能。

工程优化排独立任务：实际镜像/平台探测与共享夹具、锁缓存/普通编译复用、模块覆盖分母与串行 profile、防重复质量运行、一次清单安全归档、恢复按故障范围处理。SOURCE 交接只核本次源/契约/必要证据，不反复扫描所有历史 profile。进度以[实施事实账本](2026-10-21-delivery-progress.md)为准，不按包数或代码量虚报完成比例。
