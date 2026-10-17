# HTTP API 草案

状态：提案，尚无服务实现。机器可读入口是 [openapi.json](openapi.json)，采用 [OpenAPI 3.1](https://spec.openapis.org/oas/v3.1.1.html)。它是后续讨论、生成客户端和契约测试的起点，不能作为当前可访问的接口。

| 方法与路径 | 草案语义 |
| --- | --- |
| `POST /v1/queries` | 提交一条参数化只读 SQL，返回异步句柄；接受不代表执行成功 |
| `GET /v1/queries/{query_id}` | 查询状态；已受理任务的执行错误在句柄中返回 |
| `GET /v1/queries/{query_id}/results` | 成功后的分页结果，绑定同一结果集与身份 |
| `DELETE /v1/queries/{query_id}` | 请求取消，终态由服务器返回；成功终态不能倒退 |

`mode` 默认且仅允许 `read_only`，执行层须验证实际副作用和权限。`max_rows` 是查询总结果上限，`page_size` 只是分页大小；扫描/计算预算随运行时冻结。同步/导入/写入走后续独立的持久 Job 契约，启用前定义输入固定视图、operation ID 与提交结果对账。

draft.3 遵循对象存储湖与非 OLTP 边界，不支持业务多语句事务、行锁或未承诺的约束行为。M0/M1 仅验收 `read_consistency=published`；`read_view_id` 用于 pin 覆盖全部查询资源的已授权视图。`data_committed` 保留为后续能力草案，绑定确定已提交版本并正确补偿/等待，否则失败；不能与 `read_view_id` 合用，能力未启用时明确拒绝。

服务器规划器决定 `result_kind=data|metadata`，客户端不能自行标记。成功的数据查询句柄和每页必须包含 `read_context`，披露一致性、查询级 revision、全部源/索引版本；`published` 另必含 read view。仅常量/目录查询属于 metadata，不承诺业务数据快照。作业、发布和训练 API 尚未在本草案中定义。

结果列包含类型名；超出安全数值范围的整数、decimal、时间与二进制应按类型约定采用无损字符串表示，详细类型映射待 ADR。`next_cursor = null` 表示本结果集没有下一页；`truncated = true` 表示已因结果上限截断，不能误当完整数据。

错误结构为 `code`、`message`、`retryable`、`request_id`，兼容时附 `sqlstate`。句柄、游标都需要授权；授权令牌不能放在 URL 中。状态保留期、游标 TTL、幂等协议及身份机制的具体实现待定。

基础 `scripts/check_repository.py` 仅验证 JSON、内部引用和基本结构。完整 `harness.py check` 还执行标准 OpenAPI/JSON Schema 校验与 `tests/contracts` 的语义正反例，开发依赖由 lock 固定。它仍不验证运行时行为；真实端到端/客户端兼容测试随内核接入。

详细语义见 [查询与客户端设计](../../docs/interfaces/query-and-clients.md)。
