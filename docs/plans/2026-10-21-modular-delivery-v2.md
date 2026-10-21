# 实施策略 v2：模块交付与连续配对

2026-10-21。执行决定见 [ADR0022](../decisions/0022-module-delivery-and-validation-levels.md)。本页替代旧并行计划中的任务粒度、排程与日常门禁安排；P00–P20、I1–I3、G1–G5 的产品验收义务保留。需求以[功能矩阵](../product/requirements-v2.md)为准，模块职责与运行时权威以[模块交付合同](../design/module-delivery-contracts.md)为准。

## 当前交付目标

先使用户在主线重复得到：登记已保护固定输入 → 真实 PG 绑定 → 固定对象与 Parquet → Rust 过滤/排序/投影 → HTTP 与 PG 返回相同 ID/version。扫描链先形成可运行小片，再接 BM25/精确向量完成 I1；随后图文实际取字节与更新完成 I2，实际训练框架消费完成 I3。每个系统检查点保存教程、独立真值、负例、精确 main commit 与复现命令。

工作单位改为“需求 ID + 可消费接口 + 可验证出口”，不等待整个 P 包完成。边界经架构与消费者必要复核即实现；模块稳定即约真实配对，配对中发现的接口问题回到唯一 owner 修订。完整合同、模拟互通、模块实测、真实配对和用户系统结果分别记账。

## 四个有效槽位

| 槽位 / 具名负责人 | 当前任务及唯一文件域 | 下一职责 / 独立审查 |
| --- | --- | --- |
| ROOT：项目经理、集成与文档 | `codex/strategy-v2`，task `96cfa0969b0c48c5909ff3996afef083`；本策略、需求/模块合同、ADR、流程及进度；协调全部共享写权 | 维护关键路径、接受交接、排资源与批次、消除阻塞；入口/组合根实现；不自批自己的实现 |
| p01_oracles：产品经理、测试 | 需求粒度/正负验收、独立真值、物理 PG 官方研究及有界原型；当前只在其独占 ignored 目录准备，tracked 由 ROOT 整合 | 独审架构/用户合同，随后承担真实配对与用户系统验证；自己写的 oracle/原型由 ROOT 或架构师审 |
| plan_audit：架构师、模块开发 | 模块合同/DAG/语言迁移设计；当前独审 harness 作者的实现 | 接权后负责 storage/connectors/cluster 小片；其实现交 p00 或 ROOT 审，不继续自审 |
| p00_cf1a：模块开发、工程工具 | `codex/gates-v2`，task `972583ebc5be41069e0dd91984e06b43`；harness selector/registry、覆盖范围、证据与 CI，以及对应测试/两份先行文档 | 交付工具后接 query；common/catalog/index 按稳定点顺序接权，不同时开三个包 |

同时最多两项行为实现，保留审查能力；角色数不等于并发数。普通无污染单元、源码审查和隔离功能夹具可并行；性能测量独占同一物理资源，coverage 互斥其 target/profile，迁移/组合根有唯一窗口。端口、网络、对象前缀和数据目录必须各自隔离，不把所有测试长期串成整库窗口。

## 首批任务与集成检查点

| ID / 出口 | 唯一负责人；验收与依赖 | 下一消费者 / 阻塞解除动作 |
| --- | --- | --- |
| V2-GATES | p00；模块/配对/系统/发布选择、报告防降级、CLI/hook/CI；plan_audit 独审，ROOT 验实际命令选择与成本 | 全模块；无映射明确扩大范围，不能标模块通过 |
| V2-PRODUCT | ROOT 整合产品/架构交付物；42 条需求、唯一 owner、先行预算/错误与版本研究；p01 审架构、plan_audit 审需求 | 每个开发 DRI；未冻参数/预算的具体需求先交冻结小片，其他已闭合小片继续 |
| M-CATALOG | ROOT 闭合已验 P02 分支：`86fcaf0`，真实 PG 六轮证据已独审、task-finish/正常推送已完成；[PR14](https://github.com/yizhouxw/guradb/pull/14)已创建，双 CI/main 待闭合 | PG 父期限与对象授权配对；连接器 HTTP429仍保留；ROOT已用现有认证的标准API解除PR创建阻塞，继续跟踪CI，不阻止本地模块 |
| M-STORAGE | plan_audit 接权后验证 P03 a828：26 定向单元与真实 S3 功能/成本/故障；当前首次新窗在只读镜像预检停止，无测试结果 | P04 真源；先统一实际 backend/platform 夹具，保留旧失败，禁止反复使用过期镜像 ID |
| M-QUERY | p00 工具交接后收尾 P05 a925 部分修复：完整结果 Value 树预约、单位/真实 Arrow/DF 模块验证 | 真实 Source 消费；保留原 26 测试及新增负例、全部 11 成员/8192 负载，不等待公开入口全部实现 |
| P-OBJECT-SOURCE | plan_audit 实现、p01 测试：P03↔P04 真对象版本/批次/错误/费用；每端模块证据先稳定 | Rust query；不等 writer/训练/全部湖格式 |
| P-CONTROL-READ | ROOT 装配、catalog/storage owner 修各自实现：真实 PG 绑定/reauth→对象，同父 deadline/cancel/ledger | Source/Rust；真实暂停 PG、对象故障与撤权；同步 trait 或内存 callback 不能充当网络期限认证 |
| P-SOURCE-QUERY | ROOT 组合、两端 owner 实现：有界私有 bridge，Python 真源→Rust 唯一 SQL/Arrow/DF，完整两来源 11 成员/稳定 ID | 正式 HTTP/PG；限定 IPC/错误费用/取消与 reap 证明先复核，不另建 Python SQL 引擎 |
| S-SCAN / I1 | ROOT 批次集成，p01 独立用户旅程：先 PG→S3→Parquet→Rust 扫描端到端，再接 P06 候选/回表/正式入口完成原 I1 | I2→I3；扫描成功单列，不把它改称完整 I1 |
| R-PG-PHYSICAL | p01 研究/原型，connectors DRI 接后续实现；[独立物理路径需求](../research/2026-10-21-pg-physical-ingest.md) | 目标版本/扩展/API/一致性/恢复规格；不阻塞对象湖 I1，也不拿 wire/COPY 成功替代物理导入 |

稳定点在下一调度轮、目标 30 分钟内指定 reviewer 和消费者；真实配对在下一可用资源窗口、目标 2 小时内启动。超时记录 `blocked_since/owner/reason/next_action`，超过一个工作日必须拆片或明确重排。这些是调度目标，不是数据库 SLO。ROOT 每轮主动处理等待，不让已稳定模块因未完成的大包长期空置。

## 四层验证和 CI

| 层 | 触发与范围 | 完成含义 |
| --- | --- | --- |
| module | 普通模块变更；该 owner 全部适用生产源码、语言检查、功能/负例/故障/真实性能及自身真实 PG/S3/Arrow 等依赖 | 跨模块依赖可用固定版本契约/fixture；完整模块适用行严格 100%，不缩成 changed lines；不能宣称配对或系统通过 |
| pair | 两端真实实现消费固定接口，模块稳定点或接口变化 | 核同 view/ID/version、错误/权限/取消/剩余费用及恢复；第三方未参与模块可固定替身 |
| system | 稳定小片组成集成批次、公共入口/全局风险及 main 候选 | 当前支持旅程、受影响配对及 legacy 回归；在集成窗口运行，按整个批次基点验收 |
| release | 声明部署的发布候选 | 完整 performance/stability/soak、安全、安装、升级与联合恢复；planned/missing 继续阻断 |

机器实现由 `gates-v2` 任务提供 `--level auto/module/pair/system/release`、明确 module/pair registry 和 v2 证据绑定；**此策略页本身不证明代码已生效**。pre-commit/PR 自动选实际范围；main/system 与手工 release 分开。未知 owner、未认证映射、公共合同或无法证明影响范围的变更扩大检查；显式要求过窄范围要拒绝。报告和 receipt 固定 level、模块、源闭包、命令/预算、profile 摘要与原始任务基点，模块报告不能冒充 system/release。

工程工具变更运行完整 harness 自测、选择器差异、真实 CLI/报告伪造负例及代表性模块路径；不凭空把所有工具源码加入生产覆盖分母。已有生产严格覆盖、原始性能负载/时限、Rust 有限排除和发布义务保持。门禁调整须非作者审查并给 before/after 实际选择与运行耗时；缺失映射公开列出，不把“有 registry”当已优化所有模块。

第一批保持 main 候选 system 验证，ROOT 将稳定小片聚成集成批次，减少候选次数。未经正式证据复用协议，不跨 commit 拼接旧绿色报告或 profile；先通过范围缩小、明确资源归属和锁定依赖缓存减少重复。任何复用优化都必须验证完整输入闭包、选择器/预算版本及来源，明确引用旧执行，不能伪造 fresh。

## 用结果与阻塞校准速度

每个需求分别记录 M/P/S/R 状态与精确证据；未运行记 pending，已失败保留失败及原因。报告至少给：已验功能点、真实用户链路、关键路径剩余项、阻塞 owner/起点/解除条件、等待集成分钟、验证命令耗时及首次通过率。

首次通过率 = 首次完整计划执行即通过的功能点数 / 已有首次完整执行的功能点数；环境预检、实现、oracle、门禁与证据失败分别分类，未执行不计分母。不使用最终绿次数作分子；逐重试成本保留。Rust 行为、公共合同、测试、工具分别统计变更，不把合同/工具行数算用户功能。

工程优化排独立任务：实际镜像/平台探测与共享夹具、锁缓存/普通编译复用、模块覆盖分母与串行 profile、防重复质量运行、一次清单安全归档、恢复按故障范围处理。SOURCE 交接只核本次源/契约/必要证据，不反复扫描所有历史 profile。进度以[实施事实账本](2026-10-21-delivery-progress.md)为准，不按包数或代码量虚报完成比例。
