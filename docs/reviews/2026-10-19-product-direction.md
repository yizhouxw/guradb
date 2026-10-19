# 产品方向、技术方案与用户文档复审

日期：2026-10-19。起点：`main@09f53a28dd20f3b4def88dd0dad51d257ed95f1f`，工作区干净。范围：官方产品调研、当前源码/文档只读审计及方案/手册纠偏；本轮不修改数据库代码。

## 1. 结论

用户指正成立。项目愿景并未缺席：原[产品定位](../vision.md)和[功能架构](../product/functional-architecture.md)已有多模态对象、RAG/训练流程和共同身份要求。**问题是工程切片逐渐代替产品设计与交付主线，用户文档继承了这个偏移。** 之前把九页有界实现说明作为产品手册交付，标准不足。

当前代码是有价值的正确性/接口/索引/恢复验证基础，尚不是完整多模态数据库。继续扩展某个模块、堆接口或提高覆盖率，不能自动补齐对象模型、统一查询、用户工作流、部署管理和系统参考。

纠偏保留原产品目标、湖架构/非OLTP边界与证据纪律；改变设计中心、优先级和产品验收。没有因为目标完整而把未实现能力写成已支持。

## 2. 审计证据与问题严重度

以下源码路径/行号基于任务起点；本轮未改这些源码。相对链接可定位文件，行号用于复查而非永久API。

| 严重度 / 发现 | 当前证据 | 对产品的影响 |
| --- | --- | --- |
| P0 对象模型未落地 | [retrieval.py](../../modules/index/retrieval.py)27–47：每record一个vector及最多4个仅uri/hash/size的media；[training.py](../../modules/connectors/training.py)13–25：行即样本 | 可在一行关联文字/媒体，但缺一等父版本、时空片段、多特征、样本配对/对齐模型与校验 |
| P0 两套目录与读取语义 | [Rust catalog](../../crates/guradb-catalog/src/lib.rs)17–68：启动manifest和自建read context；[PG control](../../modules/catalog/control.py)31–108：另一dataset/run/publish目录 | 同名产品需两套授权和手工pin；不能保证SQL/检索/训练同一view |
| P0 查询未共同规划 | [service.py](../../modules/query/service.py)74–117：search/scan/graph/export分支；scan仅limit | 训练不复用SQL选择，Graph不在检索计划；数据库数据准备仍缺关联/聚合 |
| P0 手册按工程组装组织 | 起点docs/user共9文件342行；usage42行；installation要求PG/snapshot/features/hash后跳design | 用户无法从自有多模态数据独立走到检索证据和训练消费 |
| P1 规模基础有界 | [retrieval.py](../../modules/index/retrieval.py)68–98每次全读bundle；[distributed.py](../../modules/query/distributed.py)20–24、62、80等汇总rows/样本 | 多worker仍不能消除协调器全量装载，不能据此承诺水平扩展 |
| P1 长期生命周期缺失 | [control.py](../../modules/catalog/control.py)58的128 run上限及152–161退役；[snapshot.py](../../modules/query/snapshot.py)125–126 | 产物目录可回收但历史run仍保留；不能持续清理历史/operation，调高常量不是管理方案 |
| P1 物化产物重复 | [snapshot.py](../../modules/query/snapshot.py)84–95及现有v1/v2兼容 | JSON/Tantivy/全局/分片ANN需质量成本和旧视图窗口后收敛 |

既有[2026-10-18复审](2026-10-18-capability-architecture.md)其实已记录部分缺口。本轮新增的是产品完整性、统一对象/管理/查询主线与手册完成标准，不把旧发现包装成新实现。

## 3. 调研改变了哪些判断

完整证据、版本/edition边界和统计口径见[八个产品调研](../research/2026-10-19-database-products.md)。

- Milvus 3.0已描述湖外部集合、快照与刷新；开放湖本身不是充分差异，原研究已提示该竞争范围。
- LanceDB多模态/版本/索引维护是直接参考，但OSS嵌入库与Enterprise分布式lakehouse不能混为一谈。
- Qdrant/Weaviate的复制和恢复有精确产品合同，却不等同于GuraDB固定view的语义；选型不能仅看“强一致”标签。
- Vespa/Infinity给出具体查询组合/拓扑模型，不能从三worker或多API推定同等服务能力。
- PostgreSQL/ClickHouse展示手册的语言/API精度与长期管理职责；不能只学章节名称，忽略参数、失败、恢复与版本边界。

没有做竞品性能测试，未发现被实测证明的市场空白。共同版本/权限下管理、检索与训练的产品价值仍需首批业务样本检验。

## 4. 已修正的产品技术方案

| 原偏移 | 本轮改动 | 仍待实现/决策 |
| --- | --- | --- |
| 模块范围逐渐变成产品定义 | [产品合同](../product/product-contract.md)定义角色、对象关系、J1–J6旅程、最低验收 | namespace/API/DDL/坐标/错误的版本化详细设计 |
| 两套执行面被长期视为可接受状态 | [架构v0.4](../architecture.md)明确共同目录/授权/QueryContext和逐片迁移 | 真正接入SQL/HTTP、检索/关系/训练共同语义与兼容迁移 |
| 多模态等价于向量和媒体URI | 资产/片段/多特征/关系、父版本和时空定位成为产品对象 | 文本+图像首片；音视频逐模态认证，内建处理另测 |
| 数据库入口依赖内部脚本和产物 | 托管/外部接入、schema/作业/状态和对账列入M2产品门槛 | 稳定受控批接入/管理API，正式安装和配置发现 |
| A1/A2/A3替代产品路线 | [新计划](../plans/2026-10-19-product-delivery.md)映射到M2用户成果，保留原工程合同 | 每片设计/实现/质量成本证据；M3/M4不降低 |
| 组件选择代替系统架构 | 保留候选栈，明确所有者、重复物化收益和迁移窗口 | 同质量冷热I/O/RSS/恢复成本后决定收敛/替换 |

接受的方向与未决项记录在[ADR0017](../decisions/0017-product-database-and-user-manual.md)。本轮不直接替换引擎、不引入新依赖、不大改语言，也不扩大兼容声明。

## 5. 手册具体如何重建

入口按“认识产品→建模→接入→检索/训练→权限→部署/运维→参考”组织；新增[概念](../user/concepts.md)、[建模](../user/data-model.md)、[接入](../user/ingestion.md)、[检索](../user/retrieval.md)、[训练](../user/training.md)、[安全](../user/security.md)、[参考](../user/reference.md)、[生产准备](../user/production.md)及[手册建设合同](../user/manual-plan.md)。这些页面有实际概念、具体例子、语义/失败和验收内容，不是空目录。

原安装/使用/运维/诊断中真实alpha命令与限制保留。产品目标章节标待实现，现有命令链接实际契约；不给不存在的CREATE/上传API编造可执行示例。版本能力表与工程证据从主叙事移到对应参考/验证职责。

**完整产品手册仍未完成。** 自有图文贯通教程、资源管理/SQL/SDK/配置/错误逐项参考、多机/生产运维和版本兼容资料依赖尚未实现的能力。新文档页数增长只是结构变化，不是成熟度或产品完成证据。

## 6. 后续应按什么验收

第一项有限任务先冻结共同对象/目录与读取上下文，将同dataset的SQL/HTTP和媒体/特征绑定纳入用户场景。随后交付受控接入、同语义查询/证据与训练消费，A2/A3/A4作为规模和运行基础持续收口。

每项产品旅程要有独立输入真值、可复制操作、成功/负例、权限/预算、版本/兼容/恢复和实际报告。干净环境按手册完成旅程是必需证据；覆盖率、链接检查、空页或synthetic宣传数字都不能替代。发布仍需M3/M4与完整release门禁。

## 7. 本轮验证与边界

并行进行了两组官方资料调研及一组独立源码/文档审计，整合后又分别复核产品/架构与研究事实/版别。未发现P0/P1阻断；修正了四项P2：旧计划导航、简单配对能力表述过绝对、Qdrant补副本误写一般自动均衡、目录文件数被提升为职责数量。研究者未修改代码、未安装竞品。harness按任务原始base选择repository/policy/contracts/harness-tests；实际报告、最终commit和checkpoint由task receipt记录，不预填为通过。

本轮没有运行时、依赖、格式或预算变更，无数据迁移；未重跑历史数据库性能/稳定性，不推送或部署。旧证据不改绑新commit。当前完整功能/性能/长稳/HA与生产状态保持未完成。
