# 功能与技术架构复审：从有界 alpha 到下一阶段

日期：2026-10-18。审阅基点：`main@4de2fde7faf04b640ae8dbe02022e78e94db59ee`，起始工作区干净。
本页是代码、测试和本地归档的评审，不是新的运行时验收。实施顺序见[下一阶段行动计划](../plans/2026-10-18-next-stage.md)；里程碑范围仍由[路线图](../roadmap.md)定义。

后续记录：[同日 A0 集成复核](2026-10-18-a0-integration.md)已补充能力合同、独立真值、贯穿窗口的更新与 M0 原始归档。下文保留审阅基点的历史事实；R7 的现存原始文件已保全，新运行已修复日志采集顺序，但历史14份容器日志只有容器不存在错误，无法补回。R1–R6 的执行、生命周期、多机及完整质量缺口仍需后续切片。

## 1. 结论与证据等级

当前是 **M0/M1 有界 alpha，叠加部分 M2、本地三 worker/P0 集成和离线联合恢复切片**。已具备可复现的湖快照、混合检索、训练全视图导出与受控 append 闭环，值得继续沿现有事实层/发布合同演进；完整 M2、跨机器 M3 和生产 M4 均未完成。

下一阶段建议收敛为两个结果：用户能够从固定视图筛选并导出训练样本；查询与导出的协调器不再必须持有全量业务行、逐请求重读全部产物。先完成这些基础和质量测量，再决定多机运行时。暂不扩大格式、SQL 方言、媒体解码或图语言覆盖。

| 证据层 | 本次核对结果 | 不能推导的结论 |
| --- | --- | --- |
| 当前源码/合同 | 检查实际 reader、查询/训练、索引、worker、writer、目录与恢复路径，见下表 | 文件存在不等于整个能力域完成 |
| 起点 commit 的本地报告 | 归档 `d032a1095c8e95d5ffae0b590ce687f2542ab8035fb7314f13cdef7b6ce626a7` 绑定上述 HEAD、base `dba9098`，`scope=change`；9 suites、25 commands passed，归档日志摘要匹配 | `product_quality=only_selected_gates`，不是 release 通过 |
| 性能与负载 | M0/M1/M2 组件烟测、本地进程/HTTP 集成；最终 HTTP 持续负载约 62.607 秒、43轮/258请求、2次append，256→288行，OS cache 未受控 | 不是受控性能 baseline、长稳、多机容量或生产 SLO |
| 尚缺证据 | 完整 performance/stability/soak 在 policy 中仍 planned；远端新运行时 CI 未获本次核验 | 不能把本地通过写成远端或生产通过 |

报告及日志归档位于 `.git/guradb/evidence/<上述摘要>/`，原始测量/trace 的独立归档须一并保留；本地归档不等于异地备份。本次文档变更的门禁与最终 commit/checkpoint 单独由 `capability-architecture-review` 的 task receipt 记录，不复用运行时报告为文档提交背书。

12个M1/M2/P0/local v2原始证据归档逐文件摘要及commit/指纹匹配；M0三组原始结果/trace目前也可核验，但仅保留在 `artifacts/harness/20261018T054547Z-0d10c08b/`，尚未接入同一归档流程。保全缺口见R7，不能在补齐前清理这些artifacts。

## 2. 十二个功能域的完成度

“有界实现”表示明确白名单下已有代码及本地验证路径；不表示目标能力域全部完成。以下补充[功能架构](../product/functional-architecture.md)的目标清单。

| 功能域 | 当前有界实现 | 未完成或仍缺的验收 | 主要代码/合同 |
| --- | --- | --- | --- |
| F01 目录与命名空间 | PG 数据集、run/job、授权、revision/view、pin、generation/CAS | 通用 catalog、分支/标签、多项目治理、长期历史清理 | [control](../../modules/catalog/control.py)、[jobs](../../modules/catalog/jobs.py) |
| F02 湖与对象接入 | 固定 Parquet manifest；Iceberg v2 固定 metadata/snapshot，有限类型和文件数 | position/equality delete、schema/分区演进、REST Catalog、外部 Lance/Delta/Hudi；不支持项须拒绝 | [Iceberg reader](../../modules/connectors/iceberg.py)、[M1验收](../design/m1-validation.md) |
| F03 多模态资产 | 每记录外部向量、媒体 URI/hash/size，校验和受控副本 | 专门的 Segment 父版本/时空坐标模型、解码/OCR/ASR/抽帧；媒体引用不等于处理能力 | [features](../../modules/index/retrieval.py)、[snapshot](../../modules/query/snapshot.py) |
| F04 导入与同步 | Snapshot；append-only 历史校验/只读新增源文件/继承旧行版本；单机托管 append | 索引增量、Continuous、更新/删除/rewrite；writer 仅本机固定三列、32批/10000行，源提交与检索发布仍分步 | [增量](../design/m2-incremental.md)、[writer](../design/m2-writer.md) |
| F05 关系分析 | M0 参数化单表 SELECT 白名单；M1/M2 scan 仅 limit | M0 SQL 未统一进入 PG read-view 检索服务；scan 无过滤/投影，通用 JOIN/聚合及检索 SQL 未实现 | [Rust SQL](../../crates/guradb-query/src/sql.rs)、[service](../../modules/query/service.py) |
| F06 全文 | ASCII/alnum/lower；v1 Tantivy，v2 全局统计 BM25 与三份物理 postings；等值过滤/稳定排序 | v2 为 Python 文档级 JSON postings 扫描；不是已验证的高性能 Tantivy 分片路径；中文/多语言/短语未支持 | [BM25](../../modules/index/bm25.py)、[ADR0013](../decisions/0013-local-p0-partitions-and-recovery.md) |
| F07 向量 | 精确 squared-L2、Lance IVF_FLAT、过滤/源向量重排、三片候选归并、小片精确回退 | 低 probe 质量、选择性/偏斜、大于缓存回表成本；最多256维/1000候选，不代表任意模型可接入 | [ANN](../../modules/index/ann.py)、[烟测](../../tests/performance/component/m2.py) |
| F08 Graph | 固定边表 typed-edge 一跳、in/out/both、路径证据和扇出预算 | 无跨数据集节点版本解析、多跳/邻接索引；不是完整图引擎 | [Graph](../../modules/index/graph.py)、[合同](../design/m2-graph.md) |
| F09 混合检索 | BM25 + exact/ANN 的全局窗口、Top-K、RRF | Graph 与 search 是独立 job；没有统一检索→图扩展→再排序计划 | [retrieval](../../modules/index/retrieval.py)、[distributed](../../modules/query/distributed.py) |
| F10 训练数据集 | 全固定视图样本、确定性 split、manifest/Parquet、pin；三 worker 样本转换 | 请求仅 seed/train_basis_points，无样本过滤/投影/SQL 选择；协调器汇总全样本，框架/epoch/checkpoint 未实现 | [training](../../modules/connectors/training.py) |
| F11 处理/索引作业 | 持久查询状态、构建/发布对账、取消；全量索引 rebuild；有限并发 | 非通用长期作业调度；building 中断需诊断，查询重启可明确失败；无 GPU/处理 DAG | [service](../../modules/query/service.py)、[refresh](../../modules/query/incremental.py) |
| F12 治理与运维 | 数据集级授权/重授权、预算、pin/GC、本地状态检查和离线联合恢复 | TLS/远端身份、HA/PITR、审计告警、行列策略、生产升级/长稳及恢复目标 | [恢复](../design/m4-local-recovery.md)、[生产缺口](../design/production-acceptance-gaps.md) |

HTTP、CLI 与 MCP 已有薄适配；M0 SQL 服务与 M1/M2 检索作业服务仍是不同执行入口。现有客户端覆盖不能证明完整 M3，也不使本地操作者的 append/refresh/publish 自动成为公开写 API。

## 3. 技术架构评审

### R1：先解决协调器全量装载，再扩大 worker 与数据规模（最高优先）

`Service.execute` 调用 `load_bundle`；后者加载含全部 rows 的 JSON，并重读源副本、全部索引/serving shard、manifest 文件。`distributed.execute` 再排序全量 rows、建立回表映射，训练时收集全部样本。三个 worker 确实各读自己的 serving 文件，但协调器仍承受全数据规模；当前上限为10000行/32文件，不能只提高常量。

下一片应分离不可变视图描述符、产物校验生命周期和 worker 数据读取；返回有界候选/分片导出清单，按需回表。校验缓存必须绑定不可变身份与摘要，处理损坏、替换、撤权、pin/GC 和缓存失效，不能为了性能省略完整性保证。用同结果/同 recall 的前后读量、RSS和延迟证实改进。

### R2：目标技术栈与当前执行路径必须分列（高优先）

Rust/Arrow/DataFusion 是 M0 SQL 路径；Python/PyArrow 承担 M1/M2 服务、编排、部分数据处理和归并。新 v2 全文走自定义 `bm25-global-v2`，而不是 Tantivy 的分布式打分；Snapshot 同时构建 Tantivy、全局 ANN 和分片 ANN 等产物，存在存储/构建放大。serving Parquet 当前装的是 `row_json`，不等于业务列已能做列裁剪。

保留已验证的权威来源、稳定 ID、view、排序和发布合同。先统一可观察语义与读取边界，原生算子迁移逐片测量；不以“全改 Rust”作为总前置。BM25 后续在有界桥接路径与具备全局统计能力的访问结构之间做实测选型，不能静默改变评分。减少重复产物前验证旧 bundle、历史 pin、rebuild、升级/回滚。

### R3：有界生命周期需要设计退出路径（高优先）

`Control.begin` 对目录 runs 总数设128上限，GC 将旧 run 标记 retired 而不删除历史行；托管 writer 还受32批/10000行限制。这些是当前保护边界，持续新增 run 最终会拒绝服务；延长短跑不能自动证明长期可运行。

下一阶段设计历史保留/归档与 operation 对账 tombstone 的期限、容量和查询方式；不得直接删除去重记录或抬高上限。覆盖跨阈值循环、仍存 query/train/build pin、结果未知及过期 operation 重放。源 append 的 fencing 与 read-view 发布 CAS 继续分别验证；本地 flock 不能迁移成跨机器锁的承诺。

### R4：本地 HTTP 协议是多机的前置材料（高优先）

当前传输只接受 `http://127.0.0.1`，依赖共享绝对路径；HMAC、owner、持久去重、deadline/取消和进程清理已有本地测试。它没有远端对象访问、TLS/密钥轮换、节点发现、远端撤权传播或跨机器源提交 fencing。仅放开地址限制会突破现有信任边界。

多机先做一个只读固定视图任务：不可变对象引用、worker 本地读取、有限候选归并、权限与总预算贯穿。协调器重启可以让查询明确失败，写提交未知必须对账；不以透明重试掩盖副作用。

### R5：补的是用户可表达的闭环，不只是模块数量（高优先）

训练当前全视图导出，Graph 当前独立 job，媒体当前引用模型。推荐先增加固定视图上的最小过滤/投影样本选择，统一 HTTP/CLI/MCP 语义；输出选择规则、样本身份/版本、split 与 pin。同一测试验证源更新/发布期间样本不漂移。通用 SQL 融合、复杂图和内建模型处理暂缓。

### R6：组件性能/恢复与生产验收继续分开（发布阻断）

ANN 烟测为8192行/16维/8分区，8 probes 要求 recall@10≥0.95，4 probes 仅记录；不能证明近似检索在代表性负载下有收益。cold-process 不等于真冷存储。离线联合恢复要求冻结服务/外部 writer，恢复权限属于备份时点，开服前必须补撤权；它不证明 HA、PITR 或异地 DR。

本轮ANN报告只有两个查询向量，4 probes最差recall为0.9、8 probes为1.0，不能外推质量保证。P0后台只有两次append，延长duration并不会让写入贯穿全窗口；其全文/RRF和训练对照复用单节点实现，证明分布式一致性，独立算法真值仍依赖其他合同测试。完整负载需独立真值及受控更新节奏，见[workload driver](../../scripts/p0lib/workload.py)。

需冻结代表性向量维度、文本/媒体大小、过滤选择性、偏斜和并发；真正冷/热/部分命中/超过总缓存至少5次独立运行，质量与成本同时报告。完整故障 registry、soak、恢复 RPO/RTO 与远端 CI 仍是后续独立退出门槛。

### R7：补齐原始证据归档与逐场景trace（立即处理）

[M0 driver](../../scripts/m0.py)只写artifacts并打印摘要；checkpoint归档的是顶层命令日志，不能保存其引用的全部原始文件。本轮M0证据仍在，清理artifacts后将无法完整复核。应接入已有v2原始证据归档并覆盖缺件、损坏、同结果不同trace与重复运行；不能用旧commit包补作当前证据。

M2组件稳定性报告为四个checks，归档未含trace，按现行组件合同保留其有限意义。完整stability必须逐项实际注入[fault registry](../../harness/faults.toml)的12场景，记录seed、注入、源/目录状态、恢复及不变量断言，并运行verify-stability；不能把这四项checks填充成全套通过。

## 4. 本次修订与验证边界

修订功能/技术架构、路线图总状态及主要导航，区分当前实现与目标；不修改运行时代码、API schema、持久格式、依赖或质量门槛。接口/格式等早期文档中的历史提案文字须按当前运行设计及本次矩阵解读，剩余逐项对账列入行动计划。

本次验收：12个功能域有当前范围与缺口，架构发现能定位实际代码，下一阶段每片有依赖/支持拒绝边界/真值/预算/故障验收；独立复核后按实际路径运行 plan/check，提交后对原始基点复验并归档。运行时在本次未改动；本次文档门禁不新增任何数据库性能或生产支持声明。

独立复核：架构/计划与证据两轮均无阻断项；已澄清A4的Lance派生层删除/compaction验证不开放Iceberg源delete支持。plan选择contracts、harness-tests、policy、repository；最终命令报告与完成checkpoint以本任务receipt为准。
