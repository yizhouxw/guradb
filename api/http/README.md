# HTTP API：当前有界合同

状态：M0 SQL 与 M1/M2 固定视图作业均已有服务实现，属于有界 alpha；它们分别运行，尚未统一成 SQL/检索服务，也未达到完整多机或生产发布范围。

| 机器可读合同 | 当前用途 |
| --- | --- |
| [openapi.json](openapi.json)，`0.1.0-m0` | Rust/Arrow/DataFusion 的固定 Parquet manifest 只读 SQL |
| [m1-openapi.json](m1-openapi.json)，`0.2.0` | Python/PyArrow/PG 发布目录的 scan/search/graph/export jobs |
| [../capabilities/v1.json](../capabilities/v1.json) / [schema](../capabilities/v1.schema.json) | 与源码版本配套的离线支持/拒绝清单；不是 HTTP endpoint，不证明部署已启用能力 |

两份 OpenAPI 的顶层 `x-guradb-capability-manifest` 提供清单位置，path 相对 OpenAPI 源文件解析，不是 HTTP 路径；未改变请求/响应 schema。客户端应结合对应 OpenAPI、实际视图和权限解释支持范围。缺失或未知能力条目、未知清单版本不能当作支持；`GET /v1/datasets/{dataset_id}` 也不是通用能力协商端点。

## M0 SQL 查询

| 方法与路径 | 当前行为 |
| --- | --- |
| `POST /v1/queries` | 提交一条参数化只读 SQL，返回202和句柄；接受不代表执行成功 |
| `GET /v1/queries/{query_id}` | 查询状态与执行错误 |
| `GET /v1/queries/{query_id}/results` | 成功后用 cursor/page_size 读取固定结果分页 |
| `DELETE /v1/queries/{query_id}` | 请求取消；终态不倒退，非终态取消需继续读取状态 |

只支持受控 manifest 上单表 SELECT、列投影、受限比较/布尔过滤、列排序、常量 LIMIT 与值参数，类型为 `int8/text/bool`。`mode=read_only`、`read_consistency=published`，选填 `read_view_id` 必须匹配固定数据集视图。DDL/DML、事务、JOIN/聚合、函数、常量/系统目录查询、检索 SQL、PG wire 与 `data_committed` 均未支持。请求白名单由执行层校验，不能只依赖 schema。

成功句柄及每页为 `result_kind=data`，携带同一 `read_context`、manifest 源版本和空索引集合。int8 用十进制 JSON 字符串无损输出；`max_rows` 限制总结果，`page_size` 限制单页，`truncated=true` 表示因总结果上限截断。超出执行/读取/内存预算失败。

句柄/结果在有界内存保存，默认最多60秒 TTL；游标 HMAC 绑定主体、查询、view 与 offset，翻页不重跑 SQL。重启恢复固定数据视图，旧查询/结果/游标失效。具体上限、类型输入和错误见 [M0 详细设计](../../docs/design/m0-parquet-http.md) 与 [运行步骤](../../docs/design/m0-running.md)。

## M1/M2 固定视图作业

| 方法与路径 | 当前行为 |
| --- | --- |
| `POST /v1/scan` | query 仅接受 limit；没有过滤/投影或 SQL |
| `POST /v1/search` | text/vector、等值 filter、精确或显式 ANN、Top-K/RRF |
| `POST /v1/graph` | 同视图 typed-edge 一跳，方向、路径/扇出预算 |
| `POST /v1/exports` | 全视图训练导出；query 仅 seed/train_basis_points |
| `GET /v1/datasets/{dataset_id}` | 授权后读取当前发布视图的 dataset_id/name/schema/model/read_context/retention_mode |
| `GET /v1/jobs/{query_id}` | 读取持久 job 状态与错误 |
| `GET /v1/jobs/{query_id}/results` | 成功后的完整有界结果或训练 manifest；没有分页游标 |
| `GET /v1/jobs/{query_id}/parquet` | 下载成功 export 的 Parquet |
| `GET /v1/jobs/{query_id}/objects/{sha256}` | 下载该成功 export 视图中的受控媒体副本 |
| `DELETE /v1/jobs/{query_id}` | 请求取消；执行器停止后确认终态 |
| `DELETE /v1/jobs/{query_id}/retention` | 释放终态 job 及其保留；export pin 随之释放 |

POST 请求顶层为 `dataset_id`、`query` 和选填 `read_view_id`；提交绑定已授权 published view，所有结果沿用相同 context。未知字段拒绝；作业参数还会由执行器校验，因此已受理作业也可能终态失败。M1/M2 不接收 SQL 或 `read_consistency` 参数，不将 M0 的过滤/分页能力移植到 job 合同。

全文 v1 bundle 使用 Tantivy；v2 使用 `bm25-global-v2`，三份物理 JSON postings 共享全局统计，ASCII 字母数字、小写、OR token。v2 与 Tantivy 的 fieldnorm/f32 分数可能不同，版本在 context 中标明；不能宣传为同一评分或高性能 Tantivy 分布式路径。向量为精确 squared-L2 或显式内部 Lance IVF_FLAT；模型/维数必须匹配，最多256维、1000候选。Lance 是派生索引，不是外部 Lance 连接器。Graph 与 search 为独立 job，不能组成通用服务端融合计划。

export 根据 seed/稳定身份把全视图样本标为 train/validation，比例不筛掉另一 split。`filter`、`columns`、`sql` 等字段失败；当前协调器仍聚合全样本。scan 同样无过滤/投影。ANN、Graph、训练和媒体引用均不能扩展为未声明的模型处理、图语言或训练框架能力。

job 状态为 queued/running/succeeded/failed/cancelled；取消标记与完成竞争，不暴露 M0 的 cancel_requested 状态。PG 保存任务，服务重启把未终态 job 标为 failed/worker_restarted，不承诺透明恢复。成功 export 保留训练 pin，调用方完成读取后显式 release；其他终态结果也应 release 以释放有界 job 容量。详见 [M1 合同](../../docs/design/m1-snapshot-serving.md) 与 [M2 操作](../../docs/design/m2-running.md)。

## 授权、部署与兼容

Bearer token 通过 Authorization header 传递，不放 URL；状态、结果、取消、下载和 describe 均执行授权。错误字段为 code/message/retryable/request_id，已受理任务错误通过 failed 句柄返回；HTTP 成功读取状态不意味着查询成功。当前没有公开写 API 或通用 POST 幂等键，断连后重新提交可能创建新任务与新 view。

Snapshot/refresh/rebuild/publish 和托管 append 仍为可信操作者入口。refresh 只读取新增源数据文件，但旧产物复制和索引全重建仍存在；writer 仅本机固定三列、累计10000行/32批，源提交与检索发布分步。本地三 worker/loopback HTTP 依赖共享路径；没有跨机 writer fencing、HA、TLS/远端身份或水平扩展承诺。

CLI [m1.py](../../clients/cli/m1.py) 与 [MCP](../../clients/mcp/README.md) 复用 M1/M2 HTTP 合同，不新增服务端能力。当前 API 在可信网络边界运行；生产安全传输、身份和客户端互操作仍需独立验收。v1/v2 索引视图的升级/降级遵循 [ADR 0013](../../docs/decisions/0013-local-p0-partitions-and-recovery.md)，不能以代码回滚替代数据/产物恢复。

## 验证范围

`scripts/check_repository.py` 验证 JSON、引用和基本结构；contracts 门禁验证 OpenAPI/JSON Schema 与正反例。实际运行时证据分别来自 Rust、[M0 功能验收](../../docs/design/m0-validation.md)、[M1 功能验收](../../docs/design/m1-validation.md) 和 M2 合同/组件门禁，文档或 schema 通过不能代替真实执行。完整 performance/stability/soak 与生产发布仍未完成。

A0 只校正支持声明并增加离线发现合同，不改变 HTTP 路由/字段、数据布局或预算，无运行时迁移。完整接口边界、可运行与拒绝示例、历史 SQL 提案见 [查询与客户端](../../docs/interfaces/query-and-clients.md)。
