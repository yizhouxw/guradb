# 执行引擎与湖查询生态调研

状态：调研与技术提案，待 POC 和 ADR 确认；核验日期：2026-10-17。本文没有可运行实现或性能结论。

本文以对象存储为持久数据基础，聚焦 AI 数据准备、训练扫描和应用检索；高并发 OLTP、实时敏感事务不在目标内。业务写入仍需持久提交、冲突检测和可恢复发布，控制面仍需少量强一致操作。

## 1. 建议及决定条件

建议先用 **Rust + Apache Arrow + DataFusion** 做纵向 POC，同时保留 **Trino** 作为完整分布式引擎对照组。选择前者的理由是更容易把湖扫描、检索候选、关系扩展和版本校验放入同一执行计划；这是一项工程判断，不是已测得的性能优势。

建议托管关系数据以 **Iceberg v2 + Parquet** 为第一条权威数据路径，媒体使用不可变对象引用；Lance 可以作为向量与随机读取的可重建物化层。全文和图索引独立版本化，不能各自变成新的业务事实源。该组合仍需通过第 8 节的删除、版本映射及回表成本门槛。

建议 HTTP 先行、PostgreSQL 18 作为 SQL/类型比较基线，按子集验收；线协议随后独立交付。单节点 POC 不证明分布式成立，分布式运行时选型也不能由 DataFusion 的存在自动推出。

若团队首要目标变成“尽快提供成熟的分布式湖 SQL”，而混合检索只需调用外部服务，Trino 路线可能更合适；若要求完整 PostgreSQL 扩展 ABI 或事务行为，本表内方案都不能直接满足，应重新评估产品范围。

## 2. 比较对象的实际边界

| 路线 | 官方定位与可复用部分 | GuraDB 仍需承担的主要部分 |
| --- | --- | --- |
| DataFusion | Rust 查询引擎库，Arrow 内存格式，SQL/逻辑优化/物理执行和扩展点 | 服务器、持久目录、权限、提交、索引、分布式控制与协议 |
| DataFusion + Ballista | 在 DataFusion 上提供 scheduler、executor、分布式计划与 shuffle | 多模态算子集成、生产运行约束、索引放置、快照发布和恢复验收 |
| DuckDB | 可嵌入分析数据库，完整单节点 SQL、优化器、执行与扩展机制 | 多节点运行时、分片协调、服务和权限；需验证扩展的深入程度 |
| Velox | C++ 执行引擎库，接收已优化计划并执行 | SQL parser、绑定/优化器、服务器、目录、分布式运行时与存储管理 |
| Trino | coordinator/worker 分布式 SQL 服务，连接器体系 | PG 兼容表面、专用检索计划/索引、多模态身份和统一版本治理 |
| 复用 StarRocks/Doris 等完整数据库 | 已有 SQL 服务、MPP、运维及存算分离能力 | 方言适配、湖事实源关系、图/检索统一计划和内核改造 |

DataFusion 的库定位及 Arrow 使用方式见[官方介绍](https://datafusion.apache.org/library-user-guide/index.html)。Ballista 的 scheduler/executor 是额外运行时，见[官方概述](https://datafusion.apache.org/ballista/user-guide/introduction.html)。

DuckDB 提供可嵌入分析及扩展机制，见[官方定位](https://duckdb.org/why_duckdb)和[扩展文档](https://duckdb.org/docs/current/extensions/overview)。Velox 官方明确不提供 SQL parser、DataFrame 层或查询优化器，见[项目说明](https://github.com/facebookincubator/velox)。Trino 的 coordinator、worker、stage、task、exchange 与连接器职责见[官方概念](https://trino.io/docs/current/overview/concepts.html)。

### 2.1 加权定性选型

评分为本项目约束下的研究判断，1 为弱、5 为强；总分按权重加权，不代表速度、成熟度或兼容性实测。DataFusion 的分布式分数计入可复用 Ballista 的可能性，同时保留集成成本。

| 评价项 | 权重 | DataFusion + 运行时候选 | DuckDB + 自建运行时 | Velox + 自建上层 | Trino 服务 | 完整 OLAP 数据库改造 |
| --- | --- | --- | --- | --- | --- | --- |
| 统一多模态与检索算子的可扩展性 | 30% | 5 | 4 | 4 | 3 | 2 |
| 湖扫描、格式与连接器基础 | 20% | 4 | 4 | 3 | 5 | 3 |
| 可复用的分布式执行基础 | 20% | 3 | 1 | 1 | 5 | 5 |
| PostgreSQL 语义接近程度 | 10% | 3 | 4 | 1 | 2 | 1 |
| 定制边界及实现控制力 | 10% | 5 | 3 | 4 | 2 | 2 |
| 首条产品链路的交付便利性 | 10% | 3 | 4 | 1 | 4 | 4 |
| 加权总分 / 5 | 100% | **4.0** | **3.3** | **2.6** | **3.7** | **2.9** |

DataFusion 与 Trino 的差距较小，结论对权重敏感：提高“复用成熟分布式服务”的权重，Trino 可以胜出。“完整 OLAP 数据库”一列用于估算改造方向，不把 StarRocks、Doris 或 ClickHouse 的具体能力混为一谈。

DuckDB 适合作为本地开发、格式正确性对照和单节点性能对照；目前不建议再围绕它自建完整 MPP 作为主线。Velox 适合已有 parser/优化器/调度体系的团队；从本项目当前阶段出发，上层补齐成本过大。

## 3. PostgreSQL 兼容不能由 parser 推出

DataFusion 官方配置中 `datafusion.sql_parser.dialect` 的默认值是 **`generic`**，可显式设为 `PostgreSQL`。因此不能写成“默认 PostgreSQL 方言”或“更换 dialect 后自动获得 PostgreSQL 兼容”。该开关主要决定语法解析，后续绑定、类型推断、函数及执行语义仍由引擎和 GuraDB 负责。[DataFusion 配置](https://datafusion.apache.org/user-guide/configs.html)

DuckDB 官方说明其方言基于 PostgreSQL，同时列出行为差异；这同样不等于 PostgreSQL 服务器、目录或扩展兼容。[DuckDB 方言说明](https://duckdb.org/docs/current/sql/dialect/overview)

| 层次 | 建议首批范围 | 需自行验证或实现的缺口 |
| --- | --- | --- |
| 解析 | SELECT、JOIN、聚合、窗口、CTE、参数与有限 DDL | 引号/大小写、关键字、转换语法、拒绝不支持语句 |
| 类型与结果 | 常用标量、时间、decimal、明确映射的 JSON/数组 | 溢出、精度、时区、NULL、排序规则、隐式转换、嵌套类型 |
| 函数/操作符 | 公开白名单与差异清单 | PostgreSQL JSON、全文、正则、日期语义不能按同名推定 |
| 系统目录 | 自有能力目录，按客户端需求补充 | `pg_catalog`、OID、会话设置、驱动探测 SQL |
| 线协议 | 后续独立评估 simple/extended query | 鉴权、类型编码、prepared statement、取消、错误与状态机 |
| 事务 | 语句或任务级提交、固定读取视图 | 不承诺 PostgreSQL 多语句事务、锁、触发器或 OLTP 隔离语义 |
| 扩展 | 可评估 pgvector 的部分 SQL 表面 | 不加载 PostgreSQL 二进制扩展，不继承其 ABI 与执行器 |

PostgreSQL 18 的官方协议章节描述 protocol **3.2**，同时说明对 3.0 的向后兼容；SQL 比较基线选 18，不要求首批线协议实现全部 3.2 行为。若先做 3.0，应单列版本声明。[PostgreSQL 18 协议](https://www.postgresql.org/docs/18/protocol.html)

建议用固定 PostgreSQL 18 实例生成结果对照集；对所有承诺语句验证结果、类型、错误和参数行为。不支持的事务指令必须明确拒绝，不能解析后静默忽略。

## 4. DataFusion 应复用什么，自建什么

官方扩展模型提供 `TableProvider` 描述表和下推能力，`ExecutionPlan` 描述分区/顺序/物理计算，`RecordBatchStream` 产出批次。湖适配器可复用前者，检索和图算子可使用后两者接入；正确报告过滤下推的 exact/inexact 语义，避免漏掉残余过滤。[自定义表提供者](https://datafusion.apache.org/library-user-guide/custom-table-providers.html)

| 层 | 建议复用 | 必须补齐的产品语义 |
| --- | --- | --- |
| 内存与数据交换 | Arrow `RecordBatch`、Parquet、IPC/Flight 的适用部分 | 公共类型契约、版本字段、流控、外部对象引用与授权 |
| SQL 与优化 | parser、逻辑/物理优化、关系算子和统计接口 | PG 兼容层、混合检索代价与重写、租户/版本约束 |
| 数据源 | Iceberg/Lance provider、文件扫描 | 固定快照绑定、源能力发现、删除、Schema 和类型保真 |
| 对象存储访问 | 成熟对象访问库与异步 range read | 凭据代理、请求预算、重试、校验、缓存与生命周期 |
| 检索 | 可集成的 ANN/全文库 | 跨分片 Top-K、过滤、召回质量、水位、删除和评分融合 |
| 集群 | 评估 Ballista 等运行时的计划分发与 exchange | 任务所有权、取消、配额、故障语义、重平衡和可观察性 |

`object_store` 提供异步对象存储抽象，可作为接入候选；它不提供 GuraDB 的目录、表快照、提交协议或对象访问权限模型。[对象存储库文档](https://docs.rs/object_store/latest/object_store/)

建议查询先将目录中的表解析为固定源快照，再生成带版本的 provider；不要让每个远端 task 独立读取“最新”。计划序列化必须包含自定义算子的版本、快照、索引清单和身份上下文，并通过可信凭据引用解析访问权，不能携带明文长期凭据。

建议新增检索物理节点返回 `(record_id, record_version, score, evidence, index_version)`，再用关系算子融合、过滤和投影。候选预算、精确/近似属性及允许读取的索引版本是计划的一部分，不能藏在 UDF 内部。

不要把网络检索当作逐行 scalar UDF：这会隐藏 I/O、批量边界和代价，也不利于取消。异步模型生成、OCR、ASR 和媒体解码以可重试后台处理任务为主，结果携带来源和模型版本；查询内模型调用另设严格预算。

### 4.1 三类检索缺口

- **全文：** Tantivy 是 Rust 全文库，官方明确分布式不在其范围；可评估其分词、倒排和 BM25，GuraDB 负责对象化段发布、跨分片评分、缓存、删改和权限过滤。其语法与 PostgreSQL `tsquery` 并不自动等价。[Tantivy 官方说明](https://github.com/quickwit-oss/tantivy)
- **向量：** Lance 的 DataFusion provider 可做基本投影/过滤和 SQL 扫描，但这不能证明自定义 SQL 会自动选用 ANN 路径。需要显式检索算子、向量空间/距离契约、过滤策略、分片候选合并以及与精确扫描的质量对照。[Lance DataFusion 集成](https://lance.org/integrations/datafusion/)
- **图：** 边表 JOIN/递归查询可验证正确性；高扇出多跳需要邻接物化、分区感知和专用执行。首批限制跳数、扇出、visited 集合、网络与时间预算；不承诺完整 Cypher/GQL 或任意图算法兼容。

全文全局统计与局部分值、ANN 分片候选截断、图跨分片扩展都会影响融合结果；不能把“每个分片各取 K 再合并”解释成所有近似检索条件下的精确全局 Top-K。

## 5. 分布式运行时：Ballista 是候选，不是完成品承诺

Ballista 官方提供 scheduler/executor 和基于阶段的分布式执行；shuffle 设计使用阶段间物化，适合与大批量计算一起评估。它可以减少重复建设，但部署成功不能证明满足多租户检索的尾延迟、故障恢复和自定义索引算子需求。[Ballista 概述](https://datafusion.apache.org/ballista/user-guide/introduction.html)、[shuffle 设计](https://datafusion.apache.org/ballista/contributors-guide/shuffle.html)

| 核验点 | POC 必须回答的问题 |
| --- | --- |
| 自定义算子 | provider、ANN、全文、图扩展能否跨进程序列化、计划及执行？ |
| shuffle | 是否全物化、能否流式，临时磁盘/对象存储的占用和清理如何？ |
| 调度与结果 | 小 Top-K、全表扫描、索引构建能否隔离；结果是否需直接访问 worker？ |
| 容错 | worker 消失、协调器重启、重复 task 时是重试、失败还是恢复；能否明确解释？ |
| 发布 | 重试任务是否可能重复提交；失去租约的旧 worker 是否仍能发布？ |
| 资源 | 背压、内存、spill、取消、超时和 scan-byte 上限是否贯穿自定义节点？ |

官方 scheduler 文档说明默认客户端直接从 executor 获取结果，也提供 result service 入口。GuraDB 需要决定统一网关如何代理、鉴权及限流，不能把内部 worker 地址直接变为公共 API 假设。[结果获取机制](https://datafusion.apache.org/ballista/user-guide/scheduler.html)

DataFusion 的官方配置还提示部分本机并行行为在独立远端 task 模式下需要不同设置。因此“本机多个 partition”与“多个机器上的 task”必须分开测试。[DataFusion 配置](https://datafusion.apache.org/user-guide/configs.html)

建议两步验证：先证明分片检索、固定快照回表和全局融合的受限分布式链路；再验证分布式 JOIN/聚合/训练扫描的 exchange。Ballista 若不能满足第一步，可保留它用于批处理，同时另评估统一运行时；不应未经成本分析就长期维护两套查询语义。

## 6. 存算分离产品可借鉴的证据

| 产品与官方证据 | 可借鉴的机制 | 不能直接推导的结论 |
| --- | --- | --- |
| [StarRocks Architecture](https://docs.starrocks.io/docs/introduction/Architecture/) | shared-data 使用对象存储/HDFS，CN 计算并缓存，FE 负责目录与规划 | 原生 segment 格式仍保留；对象存储不自动等于开放 Iceberg 权威表 |
| [Doris 存算分离](https://doris.apache.org/docs/compute-storage-decoupled/overview/) | 共享存储保留 segment 和倒排文件；BE 缓存；Meta Service 管数据层元数据 | FE/Meta Service 的边界可参考，不能照搬其写入事务或部署依赖 |
| [ClickHouse SharedMergeTree](https://clickhouse.com/docs/cloud/reference/shared-merge-tree) | 云架构将数据与共享元数据从计算节点进一步分离，Keeper 参与协调 | 该页描述 Cloud 能力；不能据此声称同样实现可直接由社区版复用 |

三者共同说明：对象存储放持久数据之后，仍要设计元数据提交、后台合并、缓存及计算调度。这是对上述机制的架构归纳，不是三款产品性能或功能等价的证明。

对 GuraDB 的建议是持久数据/索引在对象存储、可丢弃缓存和 spill 在本地，独立规划缓存预热与请求代价；扩容无需迁移权威数据，但索引放置、缓存和热点仍会产生重平衡成本。在线检索池、训练扫描池与后台构建池共享版本目录，分别管理配额。

## 7. Iceberg、Lance 与控制面的集成难点

官方 `iceberg_datafusion` 区分 catalog-backed 的 `IcebergTableProvider` 和针对固定快照的只读 `IcebergStaticTableProvider`。建议查询绑定后使用固定视图；源元数据刷新留给目录解析阶段。[Iceberg Rust provider](https://rust.iceberg.apache.org/api/iceberg_datafusion/table/index.html)

Iceberg Rust 提供可组合的文件/逻辑 writer；这证明有可复用写入构件，不证明 GuraDB 已具备完整 append、overwrite、UPDATE/MERGE、压实或冲突重试语义。官方 DataFusion 数据源说明也明确：桥接能力取决于 Iceberg Rust，不能沿用 PyIceberg 的全部能力声明。[writer 接口](https://rust.iceberg.apache.org/api/iceberg/writer/index.html)、[DataFusion 数据源限制](https://datafusion.apache.org/python/user-guide/data-sources.html)

首批读写验收按 Iceberg v2 的 position/equality delete、sequence、字段 ID 与分区演进逐项构造样本；不能只扫描 Parquet 数据文件。v3/v4 新特性另列能力，不在 v2 基线里顺带宣称支持。[Iceberg 规范](https://iceberg.apache.org/spec/)

| 集成问题 | 建议约束与待验证点 |
| --- | --- |
| 身份 | 使用应用级 `record_id + record_version`，不把文件路径/行号当永久 ID；Iceberg v2 重写后位置可能变化 |
| 索引与快照 | 清单绑定源表 UUID、snapshot ID、Schema/模型/分片版本；查询选完整覆盖视图或明确拒绝 |
| 两种布局 | Lance 是从已提交源快照构建的派生物；失败重建，禁止业务层同步双写两个事实源 |
| 回表 | 按候选批量读取投影；测量 Parquet 点查的读放大，必要字段可物化，但要保留源版本证据 |
| 数据提交 | Iceberg catalog 的 commit 为表提交事实；GuraDB 控制记录可能滞后，需要 outbox/对账与幂等状态机 |
| 跨表原子性 | 不假定 catalog 提交与 PostgreSQL 事务可原子双提交；数据集发布清单只公布已确认的版本集合 |
| GC | 查询租约、训练快照、源保留和索引引用共同约束回收；外部系统可独立删除时必须声明复现限制 |
| 依赖版本 | Arrow/DataFusion/Iceberg/Lance 的 Rust 类型与 API 版本需要联编；统一依赖或显式 IPC/FFI 桥接并测量复制 |

控制面可优先复用 PostgreSQL 管理小规模目录、任务、租约与 CAS；它不承担业务 OLTP。需要明确数据库 HA/备份恢复、CAS 冲突、任务 fencing 与发布幂等；暂不自研共识。该建议是减小早期实现面的取舍，不保证单个 PostgreSQL 实例自动满足未来海量元数据吞吐。

## 8. 可推翻本建议的 POC 门槛

以下是**拟议验收条件**，不是现有结果；延迟、吞吐和成本阈值须在测试前按业务负载与预算冻结，不能测试后挑选有利指标。

| POC | 通过门槛 | 未通过时的动作 |
| --- | --- | --- |
| 版本联编 | 锁定所有 crate/格式版本，单一接口能完成 Iceberg 固定快照扫描、Lance 查询、全文节点 | 调整版本或隔离组件；若持续阻断，重评 DataFusion 主线 |
| 数据正确性 | 与官方独立 reader 对照；append、删改、重写、Schema 演进无多读/漏读 | 收窄格式特性或使用成熟外部 writer；禁止扩大兼容声明 |
| 混合检索 | 结构过滤 + 全文 + ANN + 受限图，证据/权限/版本正确；质量相对精确基线达约定门槛 | 改索引布局/过滤策略，必要时缩小首批检索语义 |
| PG 子集 | 冻结承诺清单中的结果/类型/错误全部通过；不支持项确定拒绝 | 修兼容层或调整公开子集，不以 parser 通过代替 |
| 多节点 | 至少 3 个 worker 完成分片查询和全局归并；worker 退出/重复 task/协调器重启不混快照 | 重评 Ballista/运行时，或对失败查询明确终止并由客户端重试 |
| 对象存储成本 | 冷/热缓存分别记录 GET 次数、读放大、吞吐、尾延迟和成本；达到预先预算 | 重做分片/缓存/回表；若无法收敛，比较 Trino 与原生 serving 布局 |
| 负载隔离 | 索引构建及训练扫描并行时，在线检索在约定退化预算内且取消有效 | 隔离资源池/缓存配额，再决定是否需要独立执行路径 |
| 恢复与删除 | 发布前后崩溃、过期 worker、源删除、索引落后、GC 竞争有可复现实验且无静默错误 | 阻止设计定稿与对外支持声明 |

比较必须使用同一数据/过滤条件、硬件、对象存储区域、冷热缓存、并发和结果质量；记录构建时间、索引体积、远程读取及恢复成本。公开基准只能帮助选用例，不能代替本产品的多模态链路。

## 9. 许可、交付物与下一步

初步核验 DataFusion、Velox、Trino 主仓库为 Apache-2.0，DuckDB 为 MIT；Tantivy 主仓库为 MIT。最终采用前仍需逐版本核查 LICENSE/NOTICE、传递依赖、codec、分词词典、模型和可选扩展；宽松的主仓库许可不覆盖商业服务与所有插件。[DataFusion LICENSE](https://github.com/apache/datafusion/blob/main/LICENSE.txt)、[Velox LICENSE](https://github.com/facebookincubator/velox/blob/main/LICENSE)、[Trino LICENSE](https://github.com/trinodb/trino/blob/master/LICENSE)、[DuckDB LICENSE](https://github.com/duckdb/duckdb/blob/main/LICENSE)、[Tantivy 项目](https://github.com/quickwit-oss/tantivy)

ClickHouse Cloud 文档只作为架构证据；SharedMergeTree 及其他托管产品能力的源码可获得性和分发权需单独核查，不能由社区主仓库许可推导。Iceberg、Lance、Ballista 和对象存储依赖也需在锁定版本时补齐 SBOM 与许可清单。

下一步产出应包括：执行栈 ADR、锁定版本/许可证表、PG 子集清单、固定快照 provider 契约、自定义算子序列化契约、双提交恢复状态机及上述 POC 报告。此后才能将“首选 POC 栈”升级为“已接受实现栈”；通过 POC 也仅证明被测范围，不等于全部产品能力已实现。
