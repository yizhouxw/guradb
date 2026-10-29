# 受控单机固定 Parquet 的 Rust SQL 读取

状态：已实现并经真实HTTP核心用例验收（2026-10-29）；强化、规模和发布尚未验收。这是可信操作者预置 M0 manifest 的有界入口；完整目录登记/发布/CF1-A pin 的正式入口仍见 [fixed-entry](fixed-entry.md)。没有公开导入、授权或保留服务。

操作者按 [M0](../design/m0-running.md) 配置 manifest SHA-256、只读数据文件和 auth_file；本片仅接受本地普通 Parquet 文件，retention_mode=best-effort，操作者负责文件生命周期。manifest schema 必须有非空 text `record_id`，源全量验证其非空且唯一，不使用物理行号。每个记录的版本采用不可变 data_revision_id，文件重写时生成新 manifest/revision。旧对象缺失或摘要变化即失败，不读取 latest。

`POST /v1/fixed-queries` 使用同一 Bearer 身份，JSON 必须包含 `dataset_id`、`data_revision_id`、`read_view_id`、`sql`；可省略 `parameters`（原 M0 参数协议）、`timeout_ms`、`max_rows`。revision=`rev_<manifest sha256>`，view=`view_<manifest sha256>`，dataset 是 manifest 中 UUID。必需版本不能省略，未知字段/显式 null 拒绝。SQL 继续支持单表列投影、过滤、按列排序和常量 LIMIT，拒绝 JOIN/聚合/DDL/DML/外部文件/多语句；表名沿用 manifest table_name。所有源文件先读取并校验，不因 LIMIT 跳过完整性与稳定键检查。

提交返回 query handle，随后通过原 `GET /v1/queries/{id}` 和 `/results` 取状态/分页，DELETE 请求取消。固定入口的 handle/result 增加 binding（可信 tenant/principal、dataset、revision、view）；结果页增加与 rows 一一对应的 lineage，含 `entity_kind=record`、`record_id`、`record_version=data_revision_id`。投影可以不含 record_id，血缘依然返回。完整 int8 仍用十进制字符串，NULL 仍为 JSON null。请求体不接受身份或权限声明。

超时至多10秒（含执行排队），并发至多2，最多32句柄，结果至多1000行/2MiB，源至多32MiB，解码至多64MiB，执行内存池至多32MiB；配置和请求只可降低。稳定键去重临时空间沿用执行池上限且在 DataFusion 执行前释放。服务固定内存另含已保留结果（句柄数乘每结果上限），不承诺进程 RSS 等于内存池。句柄终态最多保留60秒，后续请求触发回收；不支持自动重试、续租和跨重启恢复。结果可能截断，以 truncated 为准。

操作者必须在服务可见路径原子替换 auth_file；本机Docker挂载更新须先核容器内SHA-256与期望一致，再视为权限发布生效。中途不可用时服务以503 auth_unavailable拒绝，不能将主机文件写入完成当作容器内已生效。每次提交、执行及结果读取复核 auth_file。源版本错误、缺文件、重复/空 record_id、schema错误和超预算都失败；失败无结果，不回落旧入口；失败时未返回stats表示费用未知，不能计为0。源/解码/执行失败后本查询持有的普通文件、Arrow批、DataFusion资源和并发permit按作用域释放；不创建 pin/lease，也不承诺取消已停止阻塞内核IO。取消返回 cancel_requested 仅表示请求已收到。此片选择源完整性失败验证资源终态，全面取消/网络故障和强化/发布验证后续开展。

旧 `/v1/queries` 和 PG 入口合同保持；新入口停用不修改源数据。重启清空句柄和分页游标，客户端重新提交必须仍指定原版本，不能视为幂等恢复。真实验收命令为 `python scripts/fixed_read_core_acceptance.py --run-dir artifacts/<new-dir>`；fixture 不代表业务/规模/性能认证。

本片作者真实fixture为4行/1201bytes，非作者额外fixture为6行/2036bytes/2文件，验证排序/分页/截断血缘、跨主体/撤权、错版本/缺源/重复键及失败资源终态。命令报告及最终源码绑定以当前任务receipt和独立审查为准；这些fixture结果不代表业务数据、性能或完整数据库发布认证。
