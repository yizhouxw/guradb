# ADR 0014：共用执行路径的有界 PostgreSQL SQL 端口

- 状态：已接受并实现有界本机切片；真实 psql/Psycopg 和 PG 组件测试本地通过，最终提交门禁以 task receipt 为准
- 日期：2026-10-18
- 关联：[接口](../interfaces/query-and-clients.md)、[路线图](../roadmap.md)、[变更计划](../design/pg-wire-change-plan.md)、[运行说明](../design/pg-wire-running.md)
- 推进：ADR 0003/0007 的 PG wire 后续项目；保留 ADR 0010 的 M0 数据、SQL 与资源边界

## 背景与问题

用户需要用 PostgreSQL 客户端和 SDK 直接连接 GuraDB SQL 端口。起始版本只提供 HTTP SQL；PostgreSQL dialect 解析与 PG18 差异测试不构成 wire 支持，M1/M2 的 PostgreSQL 控制面也不是对外查询入口。

## 备选方案

1. 仅继续提供 HTTP：实现最少，但不能满足既有 PG 客户端直接连接的需求。
2. 将客户端接到控制面 PostgreSQL：会暴露内部元数据，且不能执行 GuraDB 的 manifest/DataFusion 查询，拒绝此方案。
3. 在现有 Rust gateway 增加有界 PG 协议适配：复用身份、SQL 白名单、固定视图和执行预算，独立验收协议与驱动。选择此方案。

## 决定

增加默认关闭的 `pg_listen`，首片仅允许 loopback TCP 地址，不内建 TLS；认证使用 PG 密码交换，username 为现有 `principal_id`，password 为现有 token，database 固定为 `guradb`。token 仍通过授权文件中的 SHA-256 验证，长连接执行时重新授权。此限制只适合本机受控开发，不授权公网或共享网络明文凭据部署。

实现 PostgreSQL 3.0 的启动、simple query 和 extended query 子集，包括 Parse/Bind/Describe/Execute/Sync/Flush/Close、值参数、prepared statements、类型化结果、CancelRequest 与 ErrorResponse/SQLSTATE。协议类型限 int8/text/bool/NULL；Describe 通过共享白名单规划获取列与参数类型，不为探测元数据提前扫描数据。无法推断的参数明确失败，不猜测为 text。

HTTP 和 PG 必须进入相同查询校验/授权/执行边界，不能另建一套 SQL 执行器。SQL 仍限定 M0 单表 SELECT、列投影、比较过滤、排序与 LIMIT；事实源与固定 read view 不变。不支持的事务、DDL/DML、COPY、锁、函数、系统目录、会话设置及扩展明确拒绝。

依赖固定为 `pgwire = "=0.41.1"`，`default-features = false`，仅复用消息 codec；gateway 复用已经锁定的 bytes 1.10.1。registry Cargo.toml 已核实 pgwire 为 MIT/Apache-2.0 双许可、MSRV 1.89，兼容本仓库 Rust 1.90。Cargo.lock 增加 7 个包，未更新 Arrow/DataFusion 版本。传输和会话采用有界实现，并在解码前校验完整帧的长度、格式和字段，避免直接继承上游 server 的较大默认帧上限以及底层 decoder 对合法格式的前提。联编与既有 HTTP 回归由正式门禁验证，不以加入协议库声称新的吞吐基线。

首批用户工具为真实 `psql` 与 Psycopg 3；SDK 要求 `autocommit=True`。协议 prepared statement 与 SQL `PREPARE` 是不同能力，前者获验收不自动开放后者。遵循 PG 官方的[消息流](https://www.postgresql.org/docs/18/protocol-flow.html)和[消息格式](https://www.postgresql.org/docs/18/protocol-message-formats.html)，不由此宣称完整 PG18 服务器兼容。

## 影响与边界

- PG 连接使用已配置 manifest，不能访问控制面 PG 的表或 M1/M2 的检索/训练作业；统一检索 SQL 仍独立推进。
- PG 标准行结果不包含 HTTP 的 `read_context`/stats/分页游标；底层执行仍固定同一视图。需要可观察版本证据的客户端继续使用 HTTP 合同。
- 协议消息、连接、prepared statements、portals 与结果均须有上限；查询继续受原有扫描、解码、内存、时间与并发预算约束。PG 无 HTTP 的 `truncated` 字段，结果超限必须明确失败。
- 取消使用连接绑定的 backend key，断连不得留下无人管理的执行；执行期取消/超时返回 `57014`，结果发送途中取消/超时关闭连接以免追加损坏帧。错误后的 Sync 边界和资源释放需要负向测试。
- 无新持久格式、控制面迁移或业务写入。旧配置省略 `pg_listen` 即维持 HTTP；恢复旧二进制时删掉新增配置字段。
- 不接受“所有 SDK/ORM 都支持”的结论。新增驱动、TLS、目录探测、连接池、事务、扩展和跨机部署各自定义验收矩阵。

## 验证与后续

本轮 PG 独立子 driver 已本地通过：真实 psql/Psycopg 功能 72 项断言、组件故障 19 个 trace 事件、组件性能 10 个样本，实际命令/报告与限制见[独立复核](../reviews/2026-10-18-pg-wire.md)。功能复用独立 Python fixture/PG18 真值，覆盖认证、参数、NULL/极端整数、文本/二进制结果、撤权、取消、畸形协议和预算。子 driver 结果不包含最终 commit 指纹，整项 HTTP 回归与最终代码绑定门禁以 harness/task receipt 为准。PG 独立吞吐、TLS 与生产发布本片未验收。
