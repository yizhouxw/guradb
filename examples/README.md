# 示例

以下均为设计提案，当前没有可执行的 GuraDB 服务。

- [SQL 关系模型](sql/relational-model.sql)：以 PostgreSQL 常见类型表达资产、片段与关系，便于讨论稳定对象引用和多模态关联。不是最终数据库 schema；向量类型和专用图语法尚未确定。
- [HTTP 请求体](http/query.json)：参数化只读查询，对应 [OpenAPI 草案](../api/http/openapi.json) 的 `QueryRequest`。认证、租户及服务地址由未来客户端提供，不写入请求体。

HTTP 示例显式使用 `published` 读取策略，当前查询草案只读。SQL 表仅表达目标数据模型，其 DDL/类型不属于 M0/M1 查询白名单；逻辑 ID/版本字段不声明并发唯一/外键强约束，`jsonb` 等候选类型仍须经过 PG18 兼容验证。

媒体对象在例子中仅用逻辑引用表达。使用外部对象时还需固定不可变版本与完整性摘要、登记实际保留能力，并通过服务端访问策略解析凭证；摘要不能代替保留，见[数据合同](../docs/product/data-contracts.md)。
