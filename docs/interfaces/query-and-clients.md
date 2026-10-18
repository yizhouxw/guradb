# SQL、HTTP 与客户端接口

状态：当前源码提供 M0 只读 SQL 与 M1/M2 固定视图作业两条独立的有界 alpha 路径，尚未统一成检索 SQL 引擎。CLI/MCP 已有 M1/M2 HTTP 薄适配；完整 M2、多机 M3 与生产发布仍未完成。本文区分现有合同和文末历史提案；PG SQL 端口按独立切片接入 M0，下列合同不扩展未验收能力。

机器可读支持清单为 [api/capabilities/v1.json](../../api/capabilities/v1.json)，格式由 [v1.schema.json](../../api/capabilities/v1.schema.json) 定义；十二域来源见[完成度复审](../reviews/2026-10-18-capability-architecture.md)。清单随源码版本解释，是离线合同，**不是 HTTP endpoint，也不证明某个部署已启用能力**。缺失、未知条目或无法识别的清单版本不能推导为支持；部署授权、实际数据视图、索引和预算仍由服务端检查。[M0 OpenAPI](../../api/http/openapi.json) 与 [M1/M2 OpenAPI](../../api/http/m1-openapi.json) 的顶层 `x-guradb-capability-manifest` 指向这份清单，path 相对 OpenAPI 源文件解析，不是 HTTP 路径；请求/响应 schema 未因此扩展。

离线 manifest 与 schema 必须取自同一 commit。PG 整合在 v1 合同中新增必填 `boundaries.pg_wire`；旧源码快照使用其对应 schema，不能用新版 schema 验证旧清单，也不承诺跨源码版本无条件兼容。

## 1. 当前入口与执行边界

| 入口 | 已实现范围 | 明确不支持或不能推导 |
| --- | --- | --- |
| M0 `POST /v1/queries` | Rust/Arrow/DataFusion；受控固定 Parquet manifest 上的单表 SELECT 白名单；异步句柄和分页 | 不读取 M1/M2 PG published view；无 JOIN/聚合/检索 SQL、业务写入 |
| 可选 `pg_listen` SQL 端口 | M0 固定 manifest 上的同一只读 SQL；PG 3.0 simple/extended、参数和 prepared statement；已测 psql 18/Psycopg 3.2.10 | 仅 loopback、非 TLS、SDK autocommit；无系统目录、会话 SET、事务、COPY、ORM 或全部驱动兼容承诺 |
| M1/M2 `POST /v1/scan` | Python/PyArrow；固定 published view；仅 limit，按逻辑键返回行 | 无 WHERE、投影、SQL 或分页游标 |
| M1/M2 `POST /v1/search` | 全文、精确向量或显式 ANN、等值过滤、全局候选与 RRF | 无任意谓词、通用 SQL、Graph 融合计划或任意模型/维度 |
| M1/M2 `POST /v1/graph` | 同视图 typed-edge 一跳，in/out/both、路径证据与扇出限制 | 不跨数据集解析节点版本；无多跳、Cypher/GQL/PGQ 或邻接优化承诺 |
| M1/M2 `POST /v1/exports` | 全固定视图样本、确定性 split、manifest/Parquet 与训练 pin | 无过滤、投影、SQL 选择、epoch/checkpoint 或训练框架适配 |
| 可信操作者 `scripts/m1.py` | Snapshot、append-only refresh、索引重建、发布/保留管理和单机托管 append | 不属于上述 HTTP/CLI/MCP 的公开写 API；不开放外部湖写回、更新/删除或跨机器 writer |

M0 的数据视图来自启动时固定 manifest；M1/M2 的 job 在提交时绑定 PG 发布目录中的一个 view，选填 `read_view_id` 可选择仍可用且授权的 published view。两条路径都不能静默退回最新数据或忽略不支持行为；`data_committed` 不是当前可用读取模式。M1/M2 job 请求也不接受该字段。

M1/M2 的 `GET /v1/datasets/{dataset_id}`（CLI/MCP `describe`）返回 `dataset_id`、`name`、`schema`、`model`、`read_context` 和 `retention_mode`。它检查当前授权和已发布产物，未发布时失败；当前响应没有通用能力协商字段。`read_context.index_versions` 用于识别实际视图中的索引版本，不能由 schema/model 的存在推导 ANN、写入或训练选择已经可用。

## 2. M0 SQL 与类型白名单

只允许一条 SELECT，恰好一个已注册表：列投影/`*`/列别名、WHERE 比较/AND/OR/NOT/IS NULL、按列 ORDER BY 和非负常量 LIMIT。`$1..$n` 是值绑定，缺失、多余或非法参数拒绝；不能作为动态表名、列名或排序方向。实际 AST 白名单见 [sql.rs](../../crates/guradb-query/src/sql.rs)。

以下是请求形态，表与字段需已由操作者注册：

```json
{
  "sql": "SELECT id, title FROM documents WHERE id = $1 ORDER BY id LIMIT 20",
  "parameters": [{"type": "int8", "value": "1"}],
  "mode": "read_only",
  "read_consistency": "published",
  "timeout_ms": 5000,
  "max_rows": 20
}
```

当前类型只有 nullable `int8/text/bool`。HTTP 的 int8 输出为十进制 JSON 字符串；text/bool/NULL 分别为 string/boolean/null。HTTP 输入允许 JSON 安全整数、字符串、布尔、null，以及完整 int8 的类型化表示；PG 输入/输出使用下节的类型与编码合同。排序默认 ASC NULLS LAST / DESC NULLS FIRST，字符串按 UTF-8/C 对照。未覆盖类型与转换不自动继承 PostgreSQL 或 DataFusion 能力。

CTE、JOIN、子查询、聚合、DISTINCT、集合运算、函数/表函数、文件读取、DDL/DML/COPY、锁、事务、多语句、OFFSET，以及无业务表的常量查询均在执行前拒绝。当前 HTTP 成功结果为 `result_kind=data`；HTTP 协议中的 metadata 语义不表示当前有可运行的常量/系统目录查询。完整边界、资源上限与错误见 [M0 详细设计](../design/m0-parquet-http.md)，可运行步骤见 [M0 运行说明](../design/m0-running.md)。

PostgreSQL 18 是明确子集的比较基线。SQL 方言、类型/函数、wire、系统目录/驱动、扩展 ABI 和事务分别验收；PG18 方言解析不能证明 `psql`、ORM、pgvector 或 PostgreSQL 事务兼容。

### 2.1 PG SQL 端口首片合同

此合同按 [ADR 0014](../decisions/0014-bounded-pg-wire.md) 实现；真实 psql 18/Psycopg 3.2.10 与 PG 组件子 driver 已本地通过，实际证据与限制见[复核记录](../reviews/2026-10-18-pg-wire.md)。最终提交的整项门禁与代码绑定仍以 harness/task receipt 为准；合同不扩大到未测工具或生产部署。

| 项目 | 首片边界 |
| --- | --- |
| 地址/身份 | 可选 `pg_listen`，仅 loopback IP 字面量；database=`guradb`，user=`principal_id`，password=原始 token；与 HTTP 共享授权文件并在查询执行重验 |
| 传输 | 非 TLS，仅本机受控使用，客户端 `sslmode=disable`；不提供公网/共享网络明文部署 |
| 启动 | PG 3.0；较高 minor 协商回 3.0。允许 user/database/application_name、UTF8/UTF-8 client_encoding 和空 options；未知或不支持设置明确拒绝 |
| 执行 | Simple Query 单一白名单语句；extended Parse/Bind/Describe/Execute/Sync/Flush/Close，命名/未命名 prepared statement；SDK 使用 autocommit |
| 类型 | int8/text/bool/NULL；文本和二进制参数/结果，text 含 NUL 的参数/结果报错；输入 int2/int4/varchar OID 可归并到对应 M0 类型，不能据此宣称新增 SQL 列类型 |
| 参数/元数据 | 参数类型通过同一 SQL 白名单和列上下文推断；无法推断返回 `42P18`；Describe 不扫描数据 |
| 固定视图 | 复用 M0 manifest/数据集授权；不访问控制面 PG 或 M1/M2 检索作业；PG 行结果不包含 HTTP `read_context`，需要该证据时使用 HTTP |
| 生命周期 | CancelRequest 与 backend key 绑定活动连接；执行期取消/超时返回 `57014`，发送途中取消/超时关闭连接；extended SQL 错误等待 Sync 恢复；Sync 清理 portal，prepared statement 可跨 Sync 保留 |
| 限额 | 消息 64 KiB、SQL 16 KiB、参数 64、statement 32、portal 16、名称 128 字节；认证连接 64，另留启动/取消容量 8；接收队列 8 条，溢出关闭；启动 10 秒、空闲 300 秒、一次结果发送总预算 10 秒 |
| 结果/执行 | 继承 M0 执行/扫描/解码/内存/行数与字节预算；Execute 可有界分批返回，最多保留一个暂停结果；总结果超限报错，不伪装完整成功 |

首片错误映射为：认证 `28P01`、数据库 `3D000`、权限/不可见资源 `42501`、不支持 `0A000`、参数 `22023`、无法推断参数 `42P18`、协议 `08P01`、连接容量 `53300`、资源上限 `54000`、取消/超时 `57014`。这是一组已声明映射，不构成完整 PostgreSQL 错误细节兼容。

portal 超过 `limits.retention_seconds`（默认 60 秒）后不可继续 Execute。`server_version=18.0` 只是客户端协议兼容标记，另有 `guradb_version=0.1.0`；驱动不能据此假定目录、事务或 PG18 全功能可用。

目录/会话设置、`BEGIN/COMMIT/ROLLBACK`、SQL `PREPARE`、COPY、DDL/DML、扩展、ORM/迁移探测与未列类型仍拒绝。真实 psql 18 和 Psycopg 3.2.10 的本轮验证不能外推全部客户端、连接池、BI 工具或驱动版本。

## 3. M1/M2 检索、训练与源更新

### 全文、向量与 Graph

全文查询只接受 ASCII 字母数字和空格、小写归一化、OR token；没有中文/多语言分词、短语或 PostgreSQL 全文操作符承诺。实际评分由 view 的索引版本决定：

| 视图/索引版本 | 当前执行 | 兼容边界 |
| --- | --- | --- |
| bundle v1 | Tantivy BM25 | 新程序读取旧 bundle 保留旧路径；不静默换评分 |
| bundle v2 / `bm25-global-v2` | Python 文档级 JSON postings 扫描；三份物理 postings 使用同一全局 df/长度统计；k1=1.2、b=0.75、float64；过滤在全库统计之后 | 与 Tantivy fieldnorm/f32 分数可能不同；不是已验证的高性能 Tantivy 分布式执行 |

索引 ID 在 `read_context` 中版本化。旧 v1 reader 不读取 v2 bundle；降级前须排空相关任务、保留被 pin 的产物并选择兼容视图，不能仅回退代码。详见 [ADR 0013](../decisions/0013-local-p0-partitions-and-recovery.md)。

向量默认精确 squared-L2；模型名称与维数必须匹配已发布 features，维度最多256。`vector_index="ann"` 显式使用内部 Lance IVF_FLAT，要求视图已有索引；缺失/损坏不得当成成功 ANN。源向量用于候选精确重排，三片候选全局归并，小片可明确报告 `exact-small-shard`。ANN 的候选重排不使整个检索变成精确检索。`top_k <= candidate_limit <= 1000`，`nprobes` 仅用于 ANN 且受实际 partitions 限制；烟测质量不能外推成任意负载 recall 保证。

search 的 `filter` 仅为 `{"field":"字段名","equals":值}` 等值条件；text/vector 同时提供时使用全局窗口与 RRF k=60，最终按分数和逻辑键稳定排序。Graph 是独立 job，输入同一边表中的 source/target/type 字段与 seeds，超过路径/扇出预算失败。不能把 search 输出到 graph 的客户端串联描述为服务端统一查询计划。具体请求见 [检索合同](../design/m1-snapshot-serving.md)、[ANN](../design/m2-ann.md)、[Graph](../design/m2-graph.md)。

Lance 在这里是从事实层构建的内部派生索引，固定版本并受摘要、view、pin/GC 约束；没有外部 Lance 数据集连接器，也不允许对已发布索引原地业务写入。媒体只包含受控引用、摘要、大小和副本；不意味着内建解码、OCR/ASR、抽帧或 embedding。

### 全视图训练导出

export 的 `query` 只接受 `seed` 和 `train_basis_points`，默认分别为 `"0"` 与 `8000`。它遍历固定视图全部样本，根据 seed 与稳定样本身份分配 train/validation；比例参数不删除另一 split，也不是样本筛选。Parquet 固定列为 dataset_id/entity_kind/logical_key/record_version/split/values_json/vector/media_json；`read_context`、模型和 seed 等上下文记录在配套 manifest，Parquet 文件本身不携带这些上下文，复现时必须一并保留。成功导出持有 pin，直到显式 release。

```json
{"dataset_id":"已授权数据集 UUID","query":{"seed":"experiment-1","train_basis_points":8000}}
```

加入 `filter`、`columns`、`sql` 等未知字段会失败，不能解析后忽略。scan 也只接受 `limit`；search 的过滤能力不延伸到 scan/export。三 worker 做样本转换，协调器仍聚合全样本并生成整份 Parquet，未实现流式训练选择。见 [training.py](../../modules/connectors/training.py) 与 [M1 训练合同](../design/m1-snapshot-serving.md)。

### 源 append 与本地部署

refresh 校验完整 append 历史、旧文件身份并继承旧记录版本，只向源读取新增数据文件；仍复制旧受控产物并**全量重建索引**。旧源 data GET 为零不代表总 I/O 为零，也不支持更新、删除、rewrite 或 Continuous。托管 writer 仅可信本机操作者、固定 id/title/active 三列、单批1–1000行、累计10000行/32批；源提交与检索发布分步，未知提交结果先按 operation 对账。见 [增量](../design/m2-incremental.md) 和 [writer](../design/m2-writer.md)。

M1/M2 可单服务运行或使用本地三 worker；HTTP worker 仅 loopback，依赖共享绝对路径。协调器仍加载全量 rows 并校验产物，三 worker 数量不证明水平扩展或提速。单机 flock 与 PG 目录 CAS 分别约束源提交和 view 发布；不能推导跨机 fencing、HA、通用 shuffle/spill、TLS/远端身份或生产容量。运行步骤见 [M2 操作](../design/m2-running.md) 和 [本地 HTTP worker](../design/local-worker-http.md)。

## 4. 句柄、授权与客户端

M0 `queries` 与 M1/M2 `jobs` 都是异步接受；HTTP 202 不表示任务成功。状态/错误/结果需继续读取，取消与完成可以竞争，终态不可倒退。两者有不同的生命周期，不能互换：

| 合同 | M0 queries | M1/M2 jobs |
| --- | --- | --- |
| 状态 | queued/running/cancel_requested/succeeded/failed/cancelled | queued/running/succeeded/failed/cancelled；取消请求不产生公开 cancel_requested 状态 |
| 结果 | 内存固定结果集，HMAC 游标分页；max_rows 控制总结果、page_size 控制单页 | 有界完整 JSON 结果，export 另有 Parquet/媒体下载；没有分页参数 |
| 保留/重启 | 默认最多60秒 TTL；重启后旧句柄/结果/游标失效 | PG 持久 job；重启把未终态 job 标为 failed/worker_restarted；终态可 release |
| 固定视图 | manifest 派生的 published context，空 index_versions | 提交固定 published context；成功 export 持续 pin |

HTTP 数据结果包含实际 `read_context`，M0 翻页沿用同一结果集；PG 行结果不携带该字段，也不使用 HTTP 句柄或游标。结果为空或截断不允许伪造数据版本。`truncated` 必须按对应合同解释；超时/内存/读取/执行预算超限失败，不把部分执行当完整成功。HTTP 身份来自 Bearer token；PG 使用 principal_id 和 token 密码。数据集授权与句柄主体检查在服务端执行，状态/结果/取消/下载重新授权。当前 alpha 无内建生产 TLS/OIDC；部署须遵守可信网络边界。

HTTP 错误使用 `code/message/retryable/request_id`，已受理任务的失败通过句柄 `status=failed` 披露。GET 可在保留期内重试；POST 断连可能已创建任务，当前公共查询接口无通用幂等键，重新提交可能绑定新 view。操作者源写入的持久 operation 对账不能由只读 POST 重试代替。

当前 CLI 为 [clients/cli/m1.py](../../clients/cli/m1.py)，支持 scan/search/graph/export、describe/status/cancel/release；提交默认等待并取结果，`--no-wait` 返回句柄，`--view` 传入固定视图。它调用公共 HTTP，不访问本地 PG/事实层，不自动重试 POST。它不是 M0 SQL CLI，也不提供公开 append/refresh/publish 命令。

MCP 为 [stdio 适配器](../../clients/mcp/README.md)，协议版本固定 `2025-03-26`；工具为 scan/search/graph/export、describe/status/results/cancel/release。提交返回 job handle，由调用方轮询；凭证只从进程环境读取。没有 resources/prompts/sampling、订阅或 notification cancellation。CLI/MCP 与 HTTP 共用授权、固定视图和预算，工具描述不扩大服务端能力，安装分发和完整客户端互操作仍需另行验收。

## 5. 历史提案与未实现目标

统一 SQL、全文、向量和 Graph 计划仍是设计方向。下例仅展示 PostgreSQL 全文语法参考，**GuraDB 当前拒绝执行**：

```sql
SELECT id, title FROM documents
WHERE to_tsvector('english', body) @@ plainto_tsquery('english', $1)
ORDER BY id LIMIT 20;
```

`tsvector/tsquery/@@` 与相关函数的含义见 [PG18 官方全文文档](https://www.postgresql.org/docs/18/functions-textsearch.html)；不能把其排名函数直接等同于 GuraDB BM25。向量 SQL 形式、[pgvector 表面兼容](https://github.com/pgvector/pgvector) 和 Graph SQL 均待独立决定与验收；兼容语法也不意味着加载扩展 ABI。

PG wire 已在 A0 之外按 [ADR 0014](../decisions/0014-bounded-pg-wire.md) 实现并验证上述有界首片；运行步骤见 [PG 端口指南](../design/pg-wire-running.md)。TLS/远程监听、系统目录/ORM、业务事务、通用 SQL 融合、训练过滤/投影和公开写 API 仍未支持；不能从 OpenAPI 的可扩展结构、server_version 或历史目标推导已支持。

## 6. 验证与兼容边界

支持清单和两份 OpenAPI 的结构/正反例由 contracts 门禁验证；M0 实际 AST/执行由 Rust 与真实 PG/Parquet/HTTP 功能测试验证，M1/M2 的 BM25、ANN、Graph、增量、writer、分片和 MCP 另有对应合同与功能测试。PG 真实客户端、协议负例、取消/断连与组件性能分别由 `tests/functional/pgwire.py`、`tests/functional/pgwire_protocol.py`、`tests/faults/component/pgwire.py` 和 `tests/performance/component/pgwire.py` 验证，证据边界见 [PG 独立复核](../reviews/2026-10-18-pg-wire.md)。入口映射见 [M0 验收](../design/m0-validation.md)、[M1 验收](../design/m1-validation.md) 和 [M2 操作](../design/m2-running.md)。

A0 的文档/离线清单校正不修改 HTTP 字段、评分算法、持久布局、支持预算或数据；无运行时迁移。新增支持声明需同时具备正例和拒绝边界证据，schema 校验不能替代真实服务验收。完整 performance/stability/soak、跨机/HA 与生产发布仍须单独完成；本分支报告不能代替整个 A0 或主线集成报告。
