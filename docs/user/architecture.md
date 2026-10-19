# 技术架构

当前存在两条分别运行的服务路径。理解这一区别有助于选择接口、部署和排查“已经发布但 SQL 看不到”的问题。

```text
M0：HTTP / 可选 loopback PG wire
       → 身份/白名单/预算 → 固定 Parquet manifest → Rust Arrow/DataFusion

M1/M2：HTTP ← CLI / MCP
       → 授权/固定 read view/作业与 pin → Python/PyArrow 检索、Graph、训练
       → 可选本机三个 worker（进程或 loopback HTTP，共享文件系统）
       → 托管事实副本 + BM25 / Lance ANN 派生产物

可信操作者 → snapshot / refresh / build → ready → CAS publish
固定 Iceberg v2 snapshot → 事实/媒体副本          ↕
                                  内部 PostgreSQL 控制目录
```

## 组件和部署含义

M0 用 Rust 实现 gateway/query/catalog/storage/connectors 和公共类型，DataFusion 执行受限查询；SQL 先经白名单转换，不开放引擎任意文件访问。manifest 由路径与 SHA-256 固定，启动时绑定；重启后旧句柄和游标失效。

M1/M2 的 Python 控制、构建、检索和训练路径使用内部 PostgreSQL 保存 dataset、run、发布 epoch、job、授权和 pin。PG 控制面不是 GuraDB SQL 端口。新 bundle 使用全局统计 BM25 三分片，ANN 为派生 Lance IVF_FLAT；旧 v1 有 Tantivy 路径，产物版本决定 reader 兼容性。

三个本机 worker 有独立进程/分片，可使用 loopback HTTP，但仍依赖同机绝对路径和共享文件系统；协调器仍收集记录并校验产物。此切片没有多机调度、HA 或一般分布式 exchange。

## 一致性与恢复边界

事实数据只有一个权威来源，派生索引不能独立接受业务写。逻辑 ID、record_version 与数据 revision 不依赖物理 rowid；read_view_id 将数据版本和索引版本绑定。源提交 fencing 与目录发布的 generation/epoch CAS 分别约束，旧构建不能覆盖新发布。

固定查询和训练消费必须遵循 pin；GC 不得删除当前发布或仍被 pin 的 run。M0 作为外部消费者读取 M1 manifest 时，需要操作者手动 pin，不能假定它自动使用 M1 的 job lease。

恢复需要一致的 PG 目录、完整本地事实/索引/媒体和训练产物副本。Git checkpoint 只恢复代码。未知提交先对账，索引损坏可从完整事实副本重建为新 run，事实丢失则先恢复备份。具体流程见[运维管理](operations.md)。

## 安全与演进

数据集授权在请求、执行和结果访问处复查；错误时拒绝访问。M0 与 M1 授权来源分别配置，不能互相推导。当前使用受控网络与 loopback，不内建生产 TLS/外部身份服务，也不是不可信文件或恶意多租户的硬隔离沙箱。

推荐目标栈中的 Iceberg/Parquet、Lance、Tantivy、PG 不表示所有格式或能力已接入。长期设计与演进依据见[总体设计](../architecture.md)、[数据合同](../product/data-contracts.md)和[ADR](../decisions/README.md)；实际白名单以[产品功能](features.md)及版本化契约为准。
