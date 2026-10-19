# 接口、类型、配置与兼容参考

状态：当前 alpha 参考导航与最小语义说明。完整逐项 SQL/函数/错误/配置参考仍待交付；下面链接中的实现契约不能由目标指南扩大。

## SQL 与客户端

| 事项 | 当前合同 |
| --- | --- |
| SQL 输入 | 单表 SELECT、列投影、比较过滤、ORDER BY、LIMIT、绑定值参数；不支持 JOIN/聚合/CTE/函数/DDL/DML |
| 数据类型 | int8、text、bool、NULL 的有界映射；PG18 为差异基线，不等于完整 PG 类型系统 |
| HTTP 整数 | int8 结果用十进制字符串；超出安全整数的参数使用显式 int8 对象 |
| PG 客户端 | psql 18 / Psycopg 3.2.10 的本机只读 autocommit；不保证 ORM/系统目录/扩展 |
| 结果版本 | HTTP read_context 固定启动清单；PG 行不携带同样 envelope，不能推定与检索目录绑定 |

SQL 用值参数传业务输入，不把用户值拼入 SQL。NULL 的受支持行为、排序/类型与错误以[SQL 运行合同](../design/m0-running.md)、[详细设计](../design/m0-parquet-http.md)和真实差异用例为准；不能从 DataFusion 上游能力推出开放函数。

PG 连接配置、simple/extended/prepared、取消和 SQLSTATE 见[PG 指南](../design/pg-wire-running.md)。业务事务、COPY、会话设置与未验收客户端仍拒绝。

## HTTP 与作业

| 接口 | 当前职责 | 权威字段/路由 |
| --- | --- | --- |
| SQL HTTP | 提交/状态/分页结果/取消 | [M0 OpenAPI](../../api/http/openapi.json) |
| 检索与训练 HTTP | describe、search/scan/graph/export、作业状态/取消/下载/释放 | [M1 OpenAPI](../../api/http/m1-openapi.json) |
| CLI / MCP | 薄适配；不应自行实现检索和授权 | [CLI](../../clients/cli/README.md)、[MCP](../../clients/mcp/README.md)、[当前使用](usage.md) |

查询/job POST 当前不是通用幂等提交；断连后已拿到 ID 时先查状态，不能盲目重复。run/operation/CAS 有独立对账合同，不能假设适用于所有 HTTP 请求。

异步受理不等于执行成功，ready 不等于 published；失败/取消后不得使用不完整结果。SQL 分页游标绑定查询与身份，不能跨查询使用；检索 scan 当前无通用分页。

## 配置和限额

当前配置分为 SQL server.json、检索控制目录/环境、worker 参数三类，默认值/生效时机见[运维](operations.md)。SQL limits 只能降低硬上限，无 spill；检索最多行/文件/维度、候选与 run 容量见[支持范围](features.md)及[离线能力合同](../../api/capabilities/v1.json)。硬上限不是吞吐承诺。

未来产品配置参考必须逐项给出类型、单位、默认、范围、作用域、是否热更新、权限、互斥项及变更影响；当前没有一个完整统一配置面，也没有全局在线能力协商接口。

## 错误与兼容

诊断时保留 query/job/run/operation、实际版本、错误类别、配置摘要和脱敏日志；不要保留 token。认证失败、语法不支持、源格式不支持、模型不符、预算超限、发布冲突、版本失效、未知提交需要不同处置，见[诊断](diagnostics.md)。稳定统一错误目录尚待设计，本文不编造错误码。

兼容至少分四轴：服务器版本与 API/schema、SQL/类型语义与 wire/客户端、源格式版本与读/写方向、持久产物与 reader/writer。旧 bundle v1/v2 和恢复流程要按[现状架构](architecture.md)、[升级准备](production.md)核对。连接成功或 JSON 可解析不等于业务兼容。
