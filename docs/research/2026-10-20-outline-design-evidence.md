# 概要设计的竞品与场景证据

核对日期：2026-10-20。状态：概要设计输入，未部署竞品、未实测性能或兼容性；不新增 GuraDB 运行时能力。本文在[前轮产品调研](2026-10-19-database-products.md)之上，实时核对影响本次设计的官方合同、限制和反例。

## 使用方法与证据边界

- `R01`—`R09` 是本轮稳定证据 ID；每条将官方观察与本项目推论分开，方案是否成立由后续工作负载/故障验证决定。
- 动态产品文档表示访问日描述，不能把 `latest`/`main` 自动绑定到某个发行包。实现前固定产品、SDK、格式及依赖版本，记录许可证与功能矩阵；没有安装证据的能力一律仍属外部文档事实。
- 不采用厂商宣传的 QPS、毫秒数或规模为本项目基线。首轮延迟、吞吐、成本、RPO/RTO 由固定输入和环境实测建立，设计预算是准入目标。
- 场景来自[产品合同](../product/product-contract.md)，不是已验证市场需求。S1 对应 J1，S2 对应 J2/J3，S3 对应 J4，S4 对应 J5，S5 对应 J6；需要首批业务样本检验统一数据库的收益。

| 场景 / 角色 | 业务问题与可观察结果 | 主要反例 / 设计约束 | 证据 |
| --- | --- | --- | --- |
| S1 湖/托管接入；数据工程师 | 现有湖表或托管批次形成可查询 revision，看到计数、schema、失败及检索就绪状态 | 源快照/删除语义不支持必须拒绝；写结果未知先对账；无键源不能承诺逐行增量 | R01、R02、R03 |
| S2 RAG 混合检索证据；应用开发者 | 同权限/版本过滤、召回、融合、关系扩展，得到原文/图像及片段坐标 | 只命中旧索引、跨模型混分、分页漂移和无权限候选不可隐瞒 | R02、R03、R04、R05 |
| S3 训练选择/复现；算法工程师 | SQL 选样、标签关联、split/seed 固定，按需读取模态且重跑一致 | 标签不能替代完整依赖保留；shuffle 要防重复/遗漏/泄漏；媒体读取不应挤占检索 | R02、R04、R07 |
| S4 增量生命周期；数据工程师/管理员 | 数据提交、索引构建和发布可观测，旧视图继续合法服务，回收可解释 | 后台任务不倒退发布；pin 不保护外部源；compaction 空间峰值和擦除责任必须可见 | R01、R02、R03、R05 |
| S5 部署治理；管理员/安全人员 | 从本机评估到私有多机，有隔离、成本、诊断、升级与联合恢复证据 | 云托管能力不能冒充 OSS；对象一致性不等于权限立即撤销；备份成功不等于完整恢复 | R04—R09 |

## 版别与比较口径

| 产品 | 本次核对口径 | 不得外推的边界 |
| --- | --- | --- |
| Milvus | 官方 3.0.x Storage V3 / external collection；[核心许可](https://github.com/milvus-io/milvus/blob/master/LICENSE)为 Apache-2.0 | Zilliz Cloud 是独立托管服务；新存储需开关且有降级限制，不能沿用 2.x 架构假设 |
| LanceDB | [产品分界](https://docs.lancedb.com/)：OSS 为 embedded retrieval library；Enterprise 为分布式多模态 lakehouse | Enterprise query nodes、plan executors、indexers 不能当作 OSS 可复用服务；本地/远端 SDK 不完全等价 |
| Qdrant | [核心许可](https://github.com/qdrant/qdrant/blob/master/LICENSE)为 Apache-2.0；分布式/一致性文档 | Cloud/Hybrid/Private Cloud 的自动化、身份和平台运维另列；本轮不证明任意版别自动补副本或再均衡 |
| Weaviate | [官方仓库许可说明](https://github.com/weaviate/weaviate#license)：Community 与 Enterprise 共仓，多数 BSD-3-Clause，`wl/` 为商业许可 | 同一个二进制包含两部分，Enterprise 需许可；Cloud/Agent 不能并为 Community 能力 |
| Vespa | [核心许可](https://github.com/vespa-engine/vespa/blob/master/LICENSE)为 Apache-2.0；自托管 container/content/config 架构 | Vespa Cloud 运维另列；查询/排序系统不能等同通用 SQL 湖数据库 |
| ClickHouse | 自托管查询诊断、角色/策略/配额文档；Cloud 与特定引擎按文档单列 | 分布式日志收集、认证和备份不能由 Cloud 行为外推自托管；本次没有产品部署测试 |
| PostgreSQL | 固定主版本 18 的 RLS 与连续归档说明 | 用来约束权限/恢复语义；不把 OLTP、完整 SQL 或扩展生态纳入 GuraDB 当前能力 |

## R01 Milvus：湖接入必须是带语义的能力矩阵

核对日期：2026-10-20；关联 S1/S4/S5、业务/技术/功能/云适配。

- **官方观察：** Storage V3 的 external source 只读；Iceberg 固定 metadata/snapshot，保留 position-delete，equality delete 不支持。Storage V3 默认关闭，新格式写入后不能直接降到不理解该格式的版本。[Storage V3](https://milvus.io/docs/storage-v3.md)
- **官方观察：** external collection 包含 schema 映射、认证和异步 manifest/refresh 流程；源变化后需要刷新。存储页还按云区分身份：S3 STS、GCS 服务账号、Azure SAS、阿里 RAM；Azure Blob 的 `iceberg-table` 明确不支持。[External Collection](https://milvus.io/docs/create-an-external-collection.md)、[云矩阵](https://milvus.io/docs/storage-v3.md#cloud-storage-and-cross-account-authentication)
- **本项目推论/目标：** 单独的 connector 名称不足以交付 S1。定义 `discover → validate → bind snapshot → commit revision → build → publish` 作业，能力按格式版本/方向/删除/schema/认证/保留共同认证；外部只读与托管写入分开授权。
- **取舍/反证：** 接入前多做校验会增加首次可用时间；用含 delete/rewrite/schema 演进和凭据过期的固定夹具证明拒绝边界。若适配器不能保护所需历史，则明确 best-effort 或复制完整依赖，不能宣布可复现。

## R02 LanceDB：版本化多模态与独立计算已是竞争范围

核对日期：2026-10-20；关联 S1—S5、技术/模块/部署/关键技术/性能。

- **官方观察：** Enterprise 将对象存储、query nodes、plan executors、indexers 及后台协调分离，可独立配置服务与重型后台工作；这些属于 Enterprise 架构。[Enterprise Architecture](https://docs.lancedb.com/enterprise/architecture)
- **官方观察：** Blob 大二进制支持按需读取；本地 Python `to_pandas(blob_mode=...)` 提供 lazy/bytes/descriptions，remote table 不支持该转换；向量/FTS/hybrid/排序查询不能通过此路径物化 Blob。[Multimodal Data](https://docs.lancedb.com/tables/multimodal)
- **官方观察：** 标签保留所指版本；标签删除后版本可被清理。重建索引期间默认用未索引行穷举补偿，`fast_search=True` 仅搜索已索引数据；compaction 可暂增磁盘占用。OSS 手动维护与 Enterprise 后台自动维护有别。[Versioning](https://docs.lancedb.com/tables/versioning)、[Reindexing](https://docs.lancedb.com/indexing/reindexing)
- **本项目推论/目标：** “湖 + 多模态 + 训练”不是市场空白。共同资产/片段/特征/revision/read view/训练选择与完整依赖 pin 才能构成 S2/S3 待验证价值；查询、训练读取和后台构建应独立限额扩缩，媒体描述与字节物化分阶段执行。
- **取舍/反证：** 额外物化只保留有收益的列和访问结构；分别计源/派生字节、构建、补扫及清理峰值。用真实媒体与冷缓存测回表/训练吞吐；若收益不足，减物化或换布局，而不将派生层变成另一主库。

## R03 Qdrant：副本一致性不是固定版本查询

核对日期：2026-10-20；关联 S1/S2/S4/S5、技术/模块/性能/恢复。

- **官方观察：** 文档分别定义写确认副本数、读 consistency 与写 ordering；写失败仍可能部分应用，需要重试。[Consistency Guarantees](https://qdrant.tech/documentation/scaling/consistency-guarantees/)
- **官方观察：** read affinity 在文档中标为 v1.19.0 起，按稳定值路由；副本变化、fan-out 和重试可改变结果，因此是 best-effort。分片数据复制与集群元数据管理分别描述。[Read Affinity](https://qdrant.tech/documentation/scaling/consistency-guarantees/#read-affinity)、[Distributed Deployment](https://qdrant.tech/documentation/scaling/distributed_deployment/)
- **本项目推论/目标：** 目录 CAS/任务租约与 worker 数据访问各有边界；幂等 job ID、提交对账和发布 fencing 不能由“有共识/副本”代替。查询和分页固定 read view，授权另有 epoch，不能靠粘性路由保持语义。
- **取舍/反证：** 固定视图增加保留、目录可用性和索引滞后成本；注入 ACK 丢失、重复提交、旧 worker 晚完成、分页间扩缩容，确认不重复、不倒退、不换成 latest。

## R04 Vespa：检索质量、计划和部署拓扑要一起设计

核对日期：2026-10-20；关联 S2/S3/S5、模块/功能/部署/性能。

- **官方观察：** stateless container 接收处理请求，content 执行存储/匹配/排序，admin/config 管配置；应用可按任务分 container 集群。[Overview](https://docs.vespa.ai/en/learn/overview.html)
- **官方观察：** 近邻指南分别给 exact/ANN、候选数量、排名表达式和多路检索。ANN 明确具有准确性、延迟和内存取舍，返回 `hits` 与送入排名的候选量不同。[Nearest Neighbor Guide](https://docs.vespa.ai/en/querying/nearest-neighbor-search-guide.html)
- **本项目推论/目标：** 查询层统一 filter/recall/fusion/rerank/evidence 的逻辑语义，worker 只执行受预算的物理片段；部署按网关/查询/批量/构建/目录分故障域。候选预算、质量与返回行数分开公开，Graph 设深度/边数上限。
- **取舍/反证：** 重排、多路召回和 fan-out 都消耗成本；固定 exact 与人工相关性真值，联合记录 recall/nDCG、冷热 p95/p99、请求/字节/内存。若质量不达标，拒绝以减候选或漏分片制造提速；若隔离收益不足，先保持同机模块化。

## R05 Weaviate：恢复单元和权限必须能核对

核对日期：2026-10-20；关联 S2/S4/S5、功能/部署/安全。

- **官方观察：** 备份按实例/collection；tenant 可随 collection 被包含，但不是独立恢复单元。当前文档说明 offloaded 租户跳过；inactive 支持自 v1.37.0，并回补 v1.35.17/v1.36.10，更早只含 active。RBAC 用户/角色被捕获但默认不恢复；v1.32.0 引入的 `rolesOptions`/`usersOptions` 默认 `noRestore`，需显式选择。版本与备份配置仍须逐项核对。[Backups](https://docs.weaviate.io/deploy/configuration/backups)
- **官方观察：** S3/GCS/Azure 备份模块支持多节点，本地 filesystem 仅单节点；文档细分 provider 认证与客户端/服务端版本要求。[Backup Providers](https://docs.weaviate.io/deploy/configuration/backups#configuration)
- **本项目推论/目标：** 联合备份清单必须覆盖目录、源快照、媒体、派生索引引用、权限/pin/任务；先定义 project/dataset 的恢复单元、恢复后的授权默认值与缺失源策略，再实现按钮/API。恢复索引可重建，但不能恢复半个合法视图。
- **取舍/反证：** 全依赖闭包备份更贵；可重建内容与必须保留字节分开列，但都需完整性断言。演练外部媒体丢失、权限遗漏、锁定对象、部分 collection/租户恢复，核对拒绝与 RPO/RTO，不能以备份任务成功作为恢复通过。

## R06 ClickHouse：性能证据与可观测性是数据库接口

核对日期：2026-10-20；关联 S2/S3/S5、性能/可观测/安全。

- **官方观察：** `system.query_log` 定义 query ID、耗时、读写/结果量、内存、异常与 profile events；分布式读量可聚合，`read_bytes` 不受缓存量影响。[query_log](https://clickhouse.com/docs/reference/system-tables/query_log)
- **官方观察：** 权限模型区分用户/角色、row policy、settings profile 与 quota；quota 按时间窗口限制资源。[Access Rights](https://clickhouse.com/docs/concepts/features/security/access-rights)
- **本项目推论/目标：** query/job/worker/source request 关联同一 trace；日志记录视图、schema、策略 epoch、候选覆盖、失败类别和预算消耗。logical scan bytes、remote bytes、cache hit bytes 分开计量，不能用逻辑读量推断云账单；按租户/负载隔离配额。
- **取舍/反证：** 全量日志/高基数标签会反噬成本并泄漏内容；指标仅放低基数维度，query ID 进入 trace/日志，SQL/对象 URL 脱敏。用超预算/取消/worker 失败验证错误及剩余任务可见，用采样丢失演练核对审计事件不会被普通 trace 采样丢弃。

## R07 PostgreSQL：权限与可恢复性需要显式例外

核对日期：2026-10-20；关联 S3/S5、安全/合规/部署。

- **官方观察：** PG18 RLS 启用后无 policy 为 default deny，但 owner/superuser/BYPASSRLS 有明确例外；跨表策略存在并发泄漏风险，文档提供负例。[Row Security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)
- **官方观察：** PITR 依赖 base backup 与连续 WAL；逻辑 dump 不能替代这套恢复链，归档失败/积压有独立监控责任。[Continuous Archiving](https://www.postgresql.org/docs/18/continuous-archiving.html)
- **本项目推论/目标：** 小型 PG 控制面权限不自动保护对象/索引/缓存/导出；共同授权上下文必须传至回表和训练读取。管理员旁路、审计、撤权和擦除分别定义；PG 恢复后还要对账源提交、视图与 pin，不能宣称单库 PITR 等于数据库整体 PITR。
- **取舍/反证：** 更强授权检查增加往返/缓存失效率；测试跨租户 join、旧索引、撤权后旧 cursor/训练句柄、日志/错误侧漏。联合恢复测目录先于/落后源快照时的拒绝和修复，权限丢失默认关闭访问。

## R08 云适配：认证、条件写和撤权不能只抽象成 URI

核对日期：2026-10-20；关联 S1/S4/S5、云厂商适配/关键技术/安全。

- **官方观察：** AWS S3 支持 `If-None-Match`/`If-Match` 条件写；冲突可返回 412/409，multipart 冲突可能需要重新发起上传。[S3 Conditional Writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)。Azure Blob 使用 ETag/If-Match，版本不符返回 412，lease 与乐观并发另有语义。[Azure Concurrency](https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage)
- **官方观察：** GCS 对象读写/list 强一致，但授予/撤销访问最终一致，缓存对象也有额外行为；不能由对象一致性推导权限立即生效。[GCS Consistency](https://docs.cloud.google.com/storage/docs/consistency)
- **官方观察：** 阿里 RAM/STS、腾讯 COS STS、华为 IAM 均有临时凭据，但身份获取、token/头部及权限条件不同；华为此处引用 EU API 示例，不外推所有区域端点。[阿里 STS](https://www.alibabacloud.com/help/en/ram/user-guide/what-is-sts)、[腾讯 COS 临时密钥](https://cloud.tencent.com/document/product/436/68283)、[华为临时身份](https://support.huaweicloud.com/eu/api-iam/iam_04_0003.html)
- **本项目推论/目标：** `ObjectStore` 与 `CredentialProvider` 端口分离；适配矩阵声明 range/condition/version/checksum/multipart、身份刷新、KMS/端点/地域和错误重试。AWS/S3-compatible 先认证，阿里 OSS/腾讯 COS/华为 OBS、Azure/GCS 各自独立切片；本研究不意味着 GuraDB 已支持它们。
- **取舍/反证：** 不以最低共同 API 掩盖差异，也不将云 SDK 暴露给 query/catalog。凭据过期、时钟偏移、断网、限流、条件冲突、KMS 拒绝和 endpoint 重定向逐 provider 验证；数据库撤权独立 fail closed，已发短期 URL 的剩余有效期/强制擦除限制必须明示。

## R09 可观测与合规的补充工程依据

核对日期：2026-10-20；关联 S5，并与竞品 R05—R07 共同导出设计目标；本条不是竞品或合规认证。

- **官方观察：** OpenTelemetry 将 traces/metrics/logs 等作为不同 signals；单一日志不能替代跨进程跟踪与指标。[Signals](https://opentelemetry.io/docs/concepts/signals/)。NIST SP800-53 Rev5 提供安全与隐私控制框架，页面注明后续 release 5.2.0。[NIST Publication](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final)
- **本项目推论/目标：** 安全目标按身份、最小权限、网络/加密、审计、数据驻留、保留/擦除、备份恢复、供应链分别建控制—证据映射。部署合同固定地域、敏感数据分级、密钥/管理员职责与跨域导出政策；由适用地区/业务确定法律义务。
- **取舍/反证：** 审计保留与最小化/擦除可能冲突，应将业务内容、脱敏元数据与不可变审计分别管理并设 legal hold。用恢复旧备份、轮换密钥、禁用身份、镜像/依赖溯源和擦除依赖闭包演练验证；拥有加密/RBAC/日志不构成已获认证或符合法规的结论。

## 设计章节必须保留的证据链

| 概要设计部分 | 场景 → 证据 → 目标与方案的落点 |
| --- | --- |
| 整体业务分析 | S1—S5 → R01/R02：统一数据库价值需以完整旅程、返工/重复物化成本和用户可观察结果验证 |
| 技术架构 | S1/S2/S4 → R01—R03：唯一事实层、强一致小目录、固定 read view、异步索引与有界补偿 |
| 模块架构 | S2/S3/S5 → R02/R04：版本化端口/计划/作业上下文、独立执行与构建；禁止访问别人的内部表或产物 |
| 功能架构 | S1—S4 → R01/R02/R05：围绕资产/片段/特征/训练选择与数据管理闭环；按支持/拒绝和失败状态验收 |
| 部署架构 | S3/S5 → R02/R04/R05/R07：查询/训练/构建资源池、目录 HA、故障域、联合恢复与独立扩缩 |
| 关键技术/性能 | S2/S3/S4 → R01/R02/R04/R06：列裁剪/批回表/缓存/ANN/融合各有真值、成本、质量和撤回条件 |
| 可观测性 | S2/S4/S5 → R06/R09：SLO 与质量/覆盖/新鲜度/资源指标关联 trace/日志，告警有诊断与运行手册 |
| 云厂商适配 | S1/S5 → R01/R05/R08：统一端口与逐 provider 能力认证、短期身份、私网/KMS/区域及错误处理 |
| 安全与合规 | S1—S5 → R05/R07/R08/R09：授权传播、撤权/擦除、媒体访问、审计和数据驻留；以威胁负例与证据验收 |

研究仍缺三类证据：真实业务样本的价值/质量门槛、同环境竞品部署对照，以及目标云上的完整兼容/成本/故障测试。后续实施不能用本文的官方描述填补这些实测缺口。
