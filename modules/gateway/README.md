# Gateway

状态：技术架构 v0.3 的职责基线，推荐方案待 POC，未实现。

用户已确定 SQL 与 HTTP 入口、PostgreSQL 语法方向，以及不承载高并发 OLTP 和实时延迟敏感事务。本轮推荐 HTTP 异步任务优先、PostgreSQL 18 SQL 子集；wire protocol 是后续独立验收项目。

负责身份/会话、权限上下文、参数绑定、查询与作业句柄、预算、分页、取消、结果与错误映射。CLI/MCP 复用公共接口及服务端语义。

通过 query 执行统一 SQL/检索计划，通过 catalog 解析允许的版本；默认读取已发布 read view，响应披露实际数据/索引版本及新鲜度。提交作业的 `data_committed` 与 `search_ready` 分开报告。

M0/M1 查询 API 只读，成功数据结果强制返回版本上下文；导入/同步/发布/训练作业的持久 operation ID、输入版本和对账由独立 Job 契约定义，不能在当前查询句柄里混入写入结果。客户端按[路线图](../../docs/roadmap.md)逐步适配。

查询句柄、结果游标和取消绑定租户与主体；`read_only` 不能代替执行层校验。PG 方言语法通过不代表类型、函数、驱动、wire 或事务兼容，未支持行为应明确报错。

POC 验收参数绑定、鉴权与权限撤销、版本绑定、超时/分页/取消及客户端一致性；HTTP 草案尚不是可运行服务。

设计依据：[技术架构](../../docs/architecture.md)、[产品功能架构](../../docs/product/functional-architecture.md)、[查询与客户端](../../docs/interfaces/query-and-clients.md)、[HTTP 草案](../../api/http/openapi.json)。
