# M0 详细设计：固定 Parquet manifest 与只读 HTTP

后续 PG 协议适配见 [ADR 0014](../decisions/0014-bounded-pg-wire.md) 与 [PG 运行说明](pg-wire-running.md)，共用本文的 SQL、数据与资源边界；不回写 M0 历史验收为 PG 客户端证据。

状态：实现合同，先于运行时代码冻结；实际支持与测量以本轮验收记录为准。任务 `m0-parquet-http`，基点 `5596117798126153a7ed9cfef291824ff8096925`。

## 目标与边界

提供单进程、单表 SELECT 的可运行闭环：受控配置 → 固定 manifest → 校验对象/Parquet → Arrow 批次 → DataFusion 过滤/排序/投影 → 异步 HTTP 句柄/固定结果分页。原始事实仍在对象存储，内存只是单次查询的物化，不产生业务 writer、可变 catalog、ANN/Graph 或分布式承诺。

先实现**有界、每次完整校验的扫描**。每个对象按 manifest 固定版本/长度/摘要读取，校验后才解码并装入本次查询 MemTable。不使用 ListingTable、LIST、路径推断或直接执行用户 SQL 来发现数据。代价是每次全量下载和解码、无法超出预算处理海量数据；后续可在相同 manifest/身份合同下替换为流式 provider、范围读取与裁剪。

Rust 1.90.0、DataFusion 50.3.0、Arrow/Parquet 56.2.x 是本次固定联编候选，不等于最新版本承诺；Cargo.lock 冻结传递依赖。DataFusion 只承载表达式/关系执行，SQL 先经 PostgreSQL dialect AST 白名单转换为 DataFrame 操作，不把 parser 或所有引擎能力暴露给客户端。[DataFusion 50.3](https://docs.rs/datafusion/50.3.0/datafusion/)。

## manifest 与信任边界

启动配置仅由操作者提供：监听地址、manifest 路径及 SHA-256、auth 文件、limits。manifest JSON v1 包含 dataset_id、table_name、schema、backend、files、retention_mode。表名为小写 ASCII 标识符；schema 仅 `int8/text/bool` 及 nullable；文件固定 fragment_id、key、size_bytes、sha256，S3 可额外固定 version_id。未知字段、重复表/列/fragment/key、不合法路径/schema/摘要、超限在启动拒绝。

read view 与 data revision 由 manifest 的 SHA-256 派生，原始 manifest 必须与配置摘要相同，启动后保持不可变，不支持热刷新。每次取数验证长度和完整摘要；被覆盖/缺失/删除返回明确错误，绝不换最新继续。S3 version_id 有值时使用版本读取；未提供源端保留保护的 local/S3 引用标记 best-effort，不以内容摘要冒充历史保留。SeaweedFS 3.97 版本化桶为首个 S3 后端验收；不因此宣称 AWS/其它 S3 后端已认证。

local backend 仅用于开发/对照，root 为受控目录；key 必须相对、无 `..`，逐组件拒绝 symlink，读取前核对 canonical root 边界。操作者和本地文件系统受信任；这不提供对抗本地管理员换路径的 OS 沙箱。S3 endpoint/bucket/region 仅来自受控配置，凭据仅从环境解析，不接受请求中的 URL 或凭据。

身份采用[数据合同](../product/data-contracts.md)的无键源路径：`(manifest digest, fragment_id, row_ordinal)`，record_version 为 data revision。M0 不承诺跨版本业务主键/增量复用。稳定键编码 v1 的测试向量在公共类型层冻结；带业务键源的全局唯一性与跨版本复用留给 M1。

## SQL 与类型白名单

只允许一条 SELECT，恰好一个已注册表：列投影/`*`/列别名、WHERE 的比较/AND/OR/NOT/IS NULL、列 ORDER BY（明确方向和 NULL 次序）、非负常量 LIMIT。参数 `$1..$n` 独立绑定；拒绝缺失、多余、非法/过大参数。表达式不通过字符串拼接执行。

不支持 CTE、JOIN、子查询、聚合、DISTINCT、集合运算、函数/表函数、文件读取、DDL/DML/COPY、锁、事务、多语句及 OFFSET 等未列项目；规划时在任何对象读取之前拒绝。未引用业务表的常量查询也先拒绝。DataFrame 的 filter/sort/select/limit 顺序固定，不能把 SQL 解析通过当成授权。

输出 int8 一律十进制 JSON string，text 为 JSON string，bool 为 JSON boolean，NULL 为 JSON null。输入支持安全整数（绝对值 ≤ 2^53−1）、string、boolean、null，以及完整 int8 的 `{"type":"int8","value":"..."}`；有歧义的类型/数字拒绝。排序默认 ASC NULLS LAST / DESC NULLS FIRST，字符串采用 UTF-8/C 对照；PG18 对照明确使用 C collation。

## HTTP 与权限

复用现有四个查询路由和响应 schema：POST 返回 202/queued；worker 将状态改为 running 后执行；成功 data 句柄/每页均带 published、revision、view、manifest 源版本及空 index_versions。仅支持 read_only/published，data_committed 明确 unsupported。read_view_id 必须匹配查询数据集的固定视图。

Bearer token 在受控 auth JSON 中只保存 SHA-256，绑定 tenant/principal 与数据集 allowlist。每次提交/状态/分页/取消重新读取授权文件，跨主体句柄返回 404；撤权独立于结果缓存生效。auth 文件错误时 fail closed，不回退旧权限。服务仅在可信网络或受保护的反向代理后使用，默认 loopback；不内建 TLS/OIDC。

查询 queued → running → succeeded/failed，取消为 cancel_requested → cancelled；终态不可倒退，worker 在停止后确认 cancelled。超时/取消覆盖下载、批次解码和 DataFusion stream；同步单批解码有协作取消边界，不承诺抢占任意 CPU 指令。每次查询产生固定内存结果，翻页不重跑 SQL；游标用进程内随机密钥 HMAC 绑定主体/查询/视图/offset。重放同一游标得到同一页；篡改/跨主体/过期拒绝。

默认 TTL 60 秒，句柄/结果有容量上限；过期清理且有界 tombstone，已知过期 410、未知/重启丢失 404。M0 句柄/运行任务非持久；进程重启后从同一 manifest 恢复数据视图，但不恢复旧查询、结果和游标。M1 才引入持久作业控制面。

## 资源和错误合同

默认启动上限：manifest 256 KiB、文件数 32、schema 列 64、单次扫描 32 MiB、Parquet 未压缩/解码 64 MiB、DataFusion pool 32 MiB、结果 2 MiB/1000 行、page 100 行（最大1000）、SQL 16 KiB、参数64、HTTP请求64 KiB、同时运行2、句柄总量32、默认/最大执行10秒。配置只可在受控上限范围调整，不接受客户端放大限制。成功的逻辑完整对象读取数/字节记录为 query stats（不含SDK重试/wire请求）；local read 与 S3 GET 成本分开解释。

Parquet footer/schema 和未压缩列总量在解码前检查；batch 最大4096行，实际 Arrow buffer 和结果 JSON 长度继续计量。DataFusion 使用有限内存池、不允许 spill；所有执行预算超限均失败，不返回部分成功。源校验和 schema 不符为 source_invalid；对象不可取为 source_unavailable；其余 unsupported/invalid_parameter/forbidden/timeout/resource_limit 等为脱敏结构化错误。max_rows 用额外一行判定 truncated；SQL LIMIT 本身不是截断错误。

这些是应用层有界输入/资源会计，不是完整进程内存隔离：Parquet 库内部临时分配、allocator 和基础引擎开销另计；alpha 只接收操作者认证的文件。真实性能记录 RSS，恶意文件沙箱/多租户硬配额须后续进程隔离设计，不宣称已满足生产防护。

## 模块与验证

common：manifest/limits/错误/协议和身份编码；storage：精确对象读取/校验；catalog：受控 manifest 注册/固定视图；connectors：Parquet schema/解码；query：白名单 AST/DataFusion/结果；gateway：HTTP/auth/任务/分页。使用现有 DAG，无新微服务。

验收包括：PyArrow 独立生成/读取 fixture（跨文件、NULL、极端整数），PG18 结果/排序/参数差异；HTTP鉴权/越权/只读绕过/分页/预算/取消/TTL；SeaweedFS 3.97 的版本读取、覆盖/缺失、禁止额外对象发现；重启数据视图一致而旧句柄失效。每项对应真实生产路径。

首次性能 smoke 冻结：8192行、两个文件、固定种子与多次独立请求，5次完整扫描/排序，单次≤10秒、RSS≤512 MiB、逻辑GET≤文件数、读字节等于清单总量、结果与独立真值一致。cold 指新服务且无 GuraDB 数据缓存，warm 指同进程重复请求；不声称清除了宿主/SeaweedFS 3.97页缓存。初次只记录 baseline-established，不自比较；构建成本与硬件/对象拓扑另记。故障 smoke 覆盖真实对象变更/删除/授权撤销/取消与重启，保留 trace 和 seed。

## 构建、恢复与发布限制

本机 Docker 提供官方固定 Rust 构建环境（避免依赖 Xcode 许可），CI 可用同一环境或锁定 native toolchain。rust suite 实际执行 fmt/clippy/test，functional 实际启动 HTTP/SeaweedFS 3.97/PG，性能/组件故障分别由 driver 执行并在 run_dir 存证。完整性能/fault registry/soak 仍为 planned，release 不可通过。

本切片没有业务写入/迁移，恢复代码用任务 checkpoint；配置/manifest 变更需明确新视图，旧进程句柄不能跨重启续用。运行 demo/测试仅使用合成 fixture、临时容器和随机测试凭据，结束清理本任务资源，绝不操作已有用户桶/数据。
