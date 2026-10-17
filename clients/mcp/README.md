# MCP stdio 适配器

已实现有界 MCP `2025-03-26` stdio 薄适配；数据库功能真值与权限均由公共 HTTP 服务决定。适配器只依赖 `clients.common.http.Client`，不访问 PG 或本地存储，不重新实现认证。

```sh
GURADB_URL=http://127.0.0.1:8081 GURADB_TOKEN=... .venv/bin/python -m clients.mcp.server
```

凭证与 URL 仅从进程环境读取，不是工具参数。stdout 仅输出每行一个 JSON-RPC 消息，stderr 仅作启动诊断；关闭 stdin 即退出。每条输入含换行最多65536字节，超限返回错误并终止连接；拒绝 batch、重复 JSON 字段、非有限数值、非法 ID、未知 envelope/工具参数。ID 仅非空短字符串或 JSON 安全整数；不支持 notification cancellation、resources、prompts、sampling 或订阅。

调用顺序：`initialize` → `notifications/initialized` → `tools/list`/`tools/call`；支持 `ping`。初始化版本响应固定为 `2025-03-26`；客户端不能接受此版本时应断开连接。工具列表一次完整返回，不支持 cursor。生命周期、按行 stdio 与工具内容遵循官方 [lifecycle](https://modelcontextprotocol.io/specification/2025-03-26/basic/lifecycle)、[transports](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports) 和 [tools](https://modelcontextprotocol.io/specification/2025-03-26/server/tools) 规范。

| 工具 | 参数 | HTTP |
| --- | --- | --- |
| scan/search/graph/export | dataset_id、query，选填 read_view_id | POST /v1/{scan,search,graph,exports} |
| describe | dataset_id | GET /v1/datasets/{id} |
| status/results | query_id | GET /v1/jobs/{id}[/results] |
| cancel/release | query_id | DELETE /v1/jobs/{id}[/retention] |

提交工具立即返回 HTTP job handle，不轮询、不自动重试 POST。调用方通过 status/results 继续，需取消则显式 cancel；cancel 不承诺作业已经停止。query 原样送服务端，由服务端执行自身参数白名单、固定视图、预算与授权。工具结果是 text content 内 JSON，成功为 `isError:false`，HTTP/网络失败为 `isError:true`；协议或工具参数错误为 JSON-RPC error。错误不打印配置 URL 或凭证。release 会释放服务端任务保留，不等同业务写入。

验证：`.venv/bin/python -m unittest tests.contracts.test_mcp -v`；`.venv/bin/python -m tests.functional.mcp` 检查真实 HTTP socket 加 stdio 子进程。完整集成 driver 可调用 `tests.functional.mcp.run(url, token, dataset, query=None)`，对真实数据库服务完成初始化、工具发现、describe 和异步 scan；返回句柄供集成驱动继续验证状态/结果。单独 mock HTTP transport 测试不代表数据库功能或三 worker 已通过；生产身份配置、安全传输、安装分发和客户端互操作矩阵仍需独立验收。
