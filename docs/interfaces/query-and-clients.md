# SQL、HTTP 与客户端接口

状态：**提案**。本文件描述 GuraDB 的接口设计起点，尚无服务实现；路径、字段和示例可在详细设计中调整。用户已确定 PostgreSQL 语法兼容方向、SQL 与 HTTP 接口，以及便于扩展 CLI、MCP 和 AI Agent 的目标。

本轮审查将实现入口收敛到只读查询：M0 验证固定 manifest/Parquet 上的精确扫描；M1 增加 Snapshot 发布、BM25、精确向量与 RRF；ANN、Graph、增量同步和分布式扩展按后续依赖推进。SQL 以 PG18 的明确子集为比较基线，HTTP 优先，wire protocol 后续独立验收。批量写入与同步使用另行设计的作业契约，不进入当前查询 API。具体阶段见[路线图](../roadmap.md)。

## 1. 统一入口，统一语义

SQL 和 HTTP 应进入同一套身份认证、权限检查、目录解析、计划生成与执行体系。全文、向量、Graph 与多模态检索应能够和关系过滤、连接、聚合组合，不为每种客户端建立独立的数据副本或查询规则。

建议先实现一个受限、可验证的查询闭环，再增加协议和客户端覆盖面。CLI、MCP 是服务端 API 的适配层，不单独定义存储能力、一致性或权限语义。批量导入、训练数据导出与对象传输的接口需要另行设计，不通过无限增大 SQL 请求体或 JSON 结果集解决。

## 2. PostgreSQL 兼容边界

“PostgreSQL 兼容”需要按层记录，不应作为一个全兼容承诺。本轮选择 PostgreSQL 18 为 SQL/类型比较基线；首批函数/类型白名单和结果差异通过 POC 固定，驱动矩阵随 wire protocol 单独验收。

| 兼容层 | 目标与需要决定的边界 |
| --- | --- |
| SQL 方言 | M0 从只读 SELECT、投影/过滤/排序/LIMIT、值参数与明确表达式开始；逐项验收类型、转换、NULL、排序和错误；连接/聚合及 DDL/DML 不因 parser 可解析就进入支持清单 |
| 函数与操作符 | 内置函数、全文函数、JSON、数组等分别验收；不能因解析通过就视为语义一致 |
| Wire protocol | 后续独立验收 protocol 版本、驱动和工具；PG18 SQL 基线不等于已实现 PG18 全协议 |
| 系统目录与工具 | `pg_catalog`、`information_schema`、会话设置及驱动探测查询单列矩阵；`psql`/ORM/迁移工具需实际验证 |
| 扩展 | pgvector 等扩展的 SQL 表面、二进制扩展加载及 PostgreSQL 扩展 ABI 是不同事项，均不自动继承 |
| 事务与一致性 | 支持声明范围内的表快照/作业提交和读取视图；首版不支持业务多语句事务、行锁/触发器、跨外部湖 2PC |

PostgreSQL 的 simple query 与 extended query 是不同协议路径；extended query 将解析、参数绑定和执行分开。若引入 wire protocol，需要覆盖启动认证、类型编码、prepared statements、事务状态、取消和错误响应，并明确 `COPY` 等后续范围。[官方协议说明](https://www.postgresql.org/docs/current/protocol-overview.html)

HTTP 查询入口每次提交一个只读语句，不提供持久业务事务会话；M0/M1 拒绝 DDL、DML、`BEGIN/COMMIT`、`SELECT FOR UPDATE` 及副作用函数，不能解析后忽略。读取采用固定快照/发布视图；导入与同步独立定义作业提交语义，不从 PostgreSQL SQL 兼容推导其隔离级别和事务能力。[PG18 事务隔离参考](https://www.postgresql.org/docs/18/transaction-iso.html)

## 3. 检索接口的语义先于新语法

### 3.1 全文检索

PG 全文兼容面后续评估 PostgreSQL 已有的 `tsvector`、`tsquery`、`@@` 与全文函数形态。M1 先通过独立定义的 BM25 检索语义验证闭环，不将以下 PG 语法列为 M1 前置条件。以下是**目标兼容性示例，不可在本仓库执行**，不是已实现功能：

本轮物理执行首选 Tantivy/BM25；它与 PG 全文词法、排名和操作符不自动等价。以下语法是否进入首批兼容白名单须单独验证，不能直接将 `ts_rank` 映射成 BM25 后宣称相同语义。

```sql
SELECT id, title
FROM documents
WHERE to_tsvector('english', body)
      @@ plainto_tsquery('english', $1)
ORDER BY id
LIMIT 20;
```

这些函数及操作符来自 PostgreSQL。示例中的 `english` 只用于说明语法；中文及多语言分词、词典、停用词、相关性排序与索引刷新语义需要单独设计，不能由此推导支持范围。[官方全文函数与操作符](https://www.postgresql.org/docs/current/functions-textsearch.html)

### 3.2 向量、Graph 与混合检索

| 检索能力 | 应先定义的语义 | 语法状态 |
| --- | --- | --- |
| 向量 | M1 精确基线、固定向量空间/维度、距离、过滤与预算；Lance ANN 后续独立验收 | 最终 SQL 待决；pgvector 仅评估选定表面，不加载扩展 ABI |
| Graph | 后续验证边表/邻接、有界方向/属性遍历、路径证据、环与扇出预算 | 关系表达/受限图算子优先；不作为 M0/M1 前置条件，不承诺完整 PGQ/Cypher/GQL |
| 混合检索 | 每路全局候选、RRF 首选融合、重排与确定性排序 | 物理基线已选，具体 SQL 表达与参数待细化 |
| 多模态 | 对象、片段、模态、派生特征与模型版本的关联，引用返回、访问授权、来源与快照 | 待决；模型调用与存储查询的边界需明确 |

pgvector 是独立扩展，其 `vector` 类型、距离操作符与 ANN 能力不属于 PostgreSQL 核心自动具备的接口。兼容其 SQL 表面不等于加载其二进制扩展，也不决定 GuraDB 的索引实现。[pgvector 官方仓库](https://github.com/pgvector/pgvector)

PostgreSQL 的递归 CTE 可作为有界关系遍历的语法参考；它不能证明 GuraDB 已实现专门的 Graph 索引或分布式遍历优化。[官方 WITH/递归查询说明](https://www.postgresql.org/docs/current/queries-with.html)

所有检索结果应能够追溯到源记录、对象/片段与数据版本。近似检索不得被标为精确结果；索引新鲜度、湖表快照与原始数据可见性差异需要可解释。训练数据读取还需要可复现的快照和批次语义，不能仅依赖交互式 Top-K 查询接口。

## 4. HTTP 查询 API 草案

机器可读草案见 [OpenAPI 文件](../../api/http/openapi.json)。下面的说明与该草案共同用于讨论，不构成稳定 API 承诺。

### 4.1 查询句柄与生命周期

只读查询统一采用异步句柄。提交成功表示服务器接受了任务，不表示查询已执行成功。

| 方法与路径 | 提案语义 |
| --- | --- |
| `POST /v1/queries` | 提交一个参数化只读 SQL 语句；接受后返回 `202` 和 `query_id` |
| `GET /v1/queries/{query_id}` | 读取执行状态、最终错误及可用统计 |
| `GET /v1/queries/{query_id}/results` | 通过 `cursor`、`page_size` 分页读取结果 |
| `DELETE /v1/queries/{query_id}` | 请求取消任务；返回值不意味着取消已经完成 |

状态为 `queued`、`running`、`succeeded`、`failed`、`cancel_requested`、`cancelled`。`cancel_requested` 是非终态；请求取消与任务完成可能竞争，服务端确认停止后才能报告 `cancelled`。`succeeded/failed/cancelled` 一旦成为终态就不可倒退；对终态执行 DELETE 返回 `200` 和原终态，不能重新改成 `cancel_requested`。句柄、结果保留期和过期后的响应需在 M0 实现前冻结。

导入、同步、索引构建或导出需要独立的可观察任务契约；内部可以复用调度组件，但不能直接套用只读查询状态解释提交结果。本草案没有定义上传、批写、同步、发布或训练导出 API。启用可产生持久效果的作业前，必须定义持久 operation ID、请求匹配、提交结果未知时的对账及取消与提交竞争；不能仅靠重新提交 POST 恢复。

### 4.2 请求、只读模式与参数

请求包含 `sql`、按 `$1`、`$2` 顺序绑定的 `parameters`，以及 `mode`、`timeout_ms`、`max_rows`。`mode` 默认且仅允许 `read_only`；`read_write` 是无效请求，拥有写权限也不能经此入口写入。以下请求是**接口提案示例，没有可连接服务**：

```json
{
  "sql": "SELECT id, title FROM documents WHERE id = $1 LIMIT 20",
  "parameters": ["doc-001"],
  "mode": "read_only",
  "timeout_ms": 5000,
  "max_rows": 20
}
```

`parameters` 是值绑定，不能通过字符串拼接代入 SQL。动态表名、列名和排序方向不属于值参数，应由调用方使用受控映射或经过正确引用的标识符构造。初版 JSON 值与 SQL 类型的映射、超出安全整数范围的数值、时间、二进制和向量编码均须在类型契约中明确；有歧义时不能静默猜测。

`read_consistency` 默认 `published`，固定已发布完整视图。M0 的空索引视图绑定固定 Parquet manifest；M1 再按配置绑定已完成的检索产物。`read_view_id` 可以 pin 一个覆盖查询全部数据资源的已授权视图，资源范围不符或过期则拒绝。`data_committed` 保留为后续能力草案：需要显式绑定已提交 revision，索引缺口只能在预算内正确补偿、等待或失败，不能与 `read_view_id` 合用。M0/M1 尚未验收该能力时必须以结构化 unsupported 错误拒绝，不能静默退回 published。预算、保留期和能力发现方式在对应里程碑前冻结。

服务端不能通过 SQL 首词、有无结果行或客户端声明判断只读性。例如，写 CTE、带副作用的函数或带 `RETURNING` 的写入都必须在执行前拒绝。解析/规划及执行层共同实施支持白名单、只读约束和对象权限；拒绝未支持语句的测试不可只依赖 JSON schema。未来若增加 `INSERT … SELECT` 等批式 SQL 作业，须在作业契约中定义固定输入版本的 `input_read_context`、目标写入权威及结果对账；本查询请求不承担写作业语义。

### 4.3 结果、分页与资源预算

结果包含列名与类型元数据、行数据、`result_kind`、下一页游标和截断标记。查询句柄不返回 `affected_rows/write_outcome/search_ready` 等写作业字段。大图像、音视频等对象返回受权限控制的引用和元数据，避免默认内联为大块 JSON/Base64。

成功句柄与每页结果必须包含由服务端规划器判定的 `result_kind`，请求不接受客户端自报该字段。任何读取业务数据的查询都是 `data`，包括聚合、空结果和对数据表做常量投影；仅常量求值和不读取业务数据的目录查询可为 `metadata`。`metadata` 不承诺业务数据快照且不得伪造 `read_context`；需要目录快照一致性的能力后续单独定义。

`data` 的成功句柄及每一页必须带 `read_context`：包含实际 `read_consistency`、非空 `data_revision_id`、至少一个非空源版本和实际索引版本集合；`published` 还必须有非空 `read_view_id`。精确扫描的索引集合可以为空，源版本不能为空。revision/view 是封装查询全部源选择的 opaque 上下文标识，不是误用某张表的 snapshot ID；多数据集查询须先冻结完整版本集合再执行。所有分页继承相同上下文，不宣称多源版本来自同一原子时点。

游标应不透明，绑定租户、主体、查询与结果快照，并具有保留期；翻页不重新执行 SQL，不因数据变化产生重复或遗漏。未定义稳定排序的查询不承诺跨次执行顺序。确定性分页与同分 Top-K 的次序需通过显式排序规则定义。

`page_size` 只控制单页大小，`max_rows` 控制可返回的总结果行数，不限制扫描行数。若结果因总行数上限截断，应显式标记截断，不能将其表现为完整结果。超出执行时间、扫描量、内存或已启用算子预算则报告对应失败/终止状态。服务端还应设最大响应字节数、并发与排队配额，客户端请求只能在授权上限内收紧预算。具体默认值和超限行为在对应里程碑实现前冻结。

### 4.4 身份、错误与重试

认证机制的具体选型待决；所有传输需要受保护连接。租户和角色从认证后的身份解析，不能信任请求体自报的 `tenant_id`。查询状态、游标、结果、取消和对象引用均需重新授权；审计需要关联主体、租户、请求和查询句柄，敏感 SQL 参数不默认写入日志。

统一错误字段 `code`、`message`、`retryable`、`request_id`，按需增加 `sqlstate` 与经过脱敏的 `details`。传输/认证/配额错误通过 HTTP 错误响应返回；已接受任务的执行失败必须通过 `status=failed` 和同一结构的 `error` 返回。`retryable` 表示可能具备重试条件，不承诺重新查询会得到相同版本或结果。若宣称 PostgreSQL 错误兼容，需另行明确 SQLSTATE 与协议字段的映射。[PostgreSQL 官方错误字段说明](https://www.postgresql.org/docs/current/protocol-error-fields.html)

GET 状态和结果可在保留期内重试，重试不重跑 SQL。只读 POST 发生网络中断时也可能留下未获取句柄的后台任务；客户端应限制重试次数和总预算。重新提交会创建新查询，未指定 view 时可能读取不同版本，不承诺去重或相同结果。批写/同步作业必须在独立契约中解决持久去重、提交对账、有效期和外部副作用；当前只读 API 不承诺通用 `Idempotency-Key` 或 exactly-once 执行。

## 5. CLI、MCP 与 Agent

CLI 建议封装 HTTP 的提交、等待、分页与取消，提供 JSON 输出和稳定退出码，并正确传播超时、查询句柄及服务端错误。命令名称和安装方式待实现阶段确定。PostgreSQL wire protocol 一旦具备经过验证的范围，可直接复用该范围内的 PostgreSQL 客户端；不能预先声称所有驱动可用。

MCP 建议提供元数据发现、查询提交、状态查询、受限结果读取与取消等工具。工具名称与 schema 留待详细设计。首批只读能力在 HTTP 合同稳定后接入；写入/同步工具等待独立作业 API 和授权设计。Agent 的工具描述或确认步骤不能代替数据库权限校验，工具权限、SQL 角色和租户边界共享服务端机制。

Agent 需要拿到结构化错误、可发现的能力边界、有限结果、可取消任务及来源信息。SQL、对象内容与查询结果中的文本均是待处理数据，不能提升客户端工具权限。MCP 和 CLI 都不能通过本地模式绕开服务端配额、审计或身份边界。SDK 可在 HTTP 与类型契约稳定后补充。

## 6. 后续需要决定与验证

1. 固定 PG18 基线上的 SQL/类型/函数白名单与差异；wire 阶段再验证真实驱动。
2. M0 前冻结 HTTP 参数/结果类型映射、错误码、保留期、分页快照、只读分类和资源预算；M1 固定 BM25/精确向量/RRF 的表达与结果语义。
3. 后续 ANN、Graph、增量、data_committed 与 PG wire 分别验收，不把某个扩展的全部行为作为隐含要求。
4. 在对应里程碑实现前完成导入/同步/发布/训练作业 API 详细设计：输入 pin、操作身份、对账、取消、保留、GC 与写入权威；不扩展为跨外部湖全局事务。
5. Agent 只读角色、租户隔离、预算和取消竞争；写入重试用例属于后续作业合同。

后续运行时测试覆盖参数绑定、类型往返、只读绕过、跨租户句柄/游标访问、数据/目录结果分类、上下文不缺失、分页版本相同、错误稳定性、预算超限及取消终态不倒退；wire 阶段再测试真实 PostgreSQL 驱动。当前仓库检查仅验证草案结构与正反例，不证明解析器、执行器或状态转换已实现。
