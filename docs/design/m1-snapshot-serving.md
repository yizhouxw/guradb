# M1：固定湖快照、混合检索与训练闭环

状态：实现与本地验收切片；最终代码证据以 task-finish 的原基点报告为准。路线图 M1 的有界单节点 alpha，非完整 P0 或生产发布。决策见 [ADR 0011](../decisions/0011-m1-bounded-snapshot-serving.md)，运行见 [操作说明](m1-running.md)，逐项证据见 [验收映射](m1-validation.md)。

## 可观察闭环

显式 Iceberg v2 metadata URI + SHA-256 + snapshot ID → 全量固定 Snapshot 验证/物化 → 外部文本/标签/媒体引用/embedding 注册 → Tantivy BM25、精确 L2、RRF → PG 原子发布 → HTTP/CLI 查询 → 同视图确定性训练 manifest 与 Parquet 导出。

外部湖是唯一业务写入权威。服务从不可变物化读取，不对外源 append/删除，不轮询 latest，不依赖 LIST。M0 Rust/Arrow/DataFusion 的 SQL 子集保留；M1 用独立、明确版本的 scan/search/export HTTP 路由，不新增 SQL 语法或宣称 SQL/全文/向量组合优化已实现。生成的标准 manifest 可由 M0 Rust 服务独立读取，这是互操作路径；M0 的文件授权配置不自动成为 M1 的 PG 授权来源。

## 输入白名单与拒绝

首个定位路径为受控 metadata-location，尚无 REST/Glue/Hive Catalog。local 根须为无符号链接的绝对 canonical file URI；S3 根使用显式 bucket/prefix，后端实际认证 SeaweedFS 3.97，凭据仅来自操作者环境。每次 Snapshot 显式固定 metadata 摘要和快照 ID，可选 metadata 中仍存在的历史快照；不使用 current-snapshot-id 替换调用者的选择。

仅 Iceberg v2、单 schema、单非分区 spec、空 sort order、平面 long/string/boolean、Parquet；逐文件字段 ID、顺序、名称、类型与 nullable 必须一致。源 long 映射 int8。禁止 schema/分区演进、嵌套、未支持类型/default、加密数据、position/equality delete manifest 或活跃 delete file。Avro 使用 null/deflate codec。有删除状态的**数据文件**按 Iceberg manifest 语义排除，这不表示支持逐行删除文件。先检查全部 manifest 再发出 data GET；重复 live file、NULL/重复逻辑键、缺失/变更/跨根文件与超限均失败。

稳定键由一个 long 或 string 列组成，使用数据合同规定的 v1 类型标签/长度编码；整个 Snapshot 校验唯一性。外部文本片段可表示为有稳定键的行，文本与标签来自该行；媒体与向量 sidecar 必须恰好覆盖这些键，不能添加/丢弃/按物理行序猜测映射。本切片实体种类固定 record，没有通用跨表 segment/parent/edge 管理。record_version 为整个物化 revision 的版本，未实现逐行增量继承。

## 特征、排序与质量语义

特征 JSON 由 URI/SHA 固定，严格字段为 model、dimension、metric、preprocessing、records。model 是非空模型/空间 ID；dimension 1–256，metric 固定 squared_l2，preprocessing 固定 identity-v1。每项 record 包含 logical_key、vector、media；向量为有限数字，绝对值不大于 1e6；每记录最多四个媒体引用，每引用声明 URI、SHA-256 和字节数，构建时实际读取验证。没有内建模型下载、解码或 embedding 生成。

Tantivy 0.26.0 Python binding（Rust 内核）使用冻结的 ascii-alnum-lower-v1 分析器，无停用词或词干。HTTP 文本只收最多 16 个 ASCII 字母/数字词项，按 OR 查询；不开放 Tantivy 查询语言或正则。中文/多语言分析器未认证。所有匹配都参与全局排序后才应用候选窗口；相等过滤在候选截断前应用。单路 BM25 返回原始分数，向量返回负平方 L2，二者按分数降序、逻辑键升序。双路按固定 `1/(60+rank)` RRF，候选窗口各自 1–1000，top_k 不大于窗口；响应明确窗口，不承诺候选窗口以外的融合结果。

源 int64 在 HTTP values、训练 values_json 中使用十进制字符串，避免 JSON 安全整数丢失。过滤 int8 可传安全整数或 canonical 十进制字符串；不支持的过滤类型/字段失败，不做 SQL 式隐式转换。向量查询必须显式匹配 model。训练 Parquet 的固定列保存身份、record_version、split、values_json、vector、media_json；未声称保持原源表的物理布局。

## PG 状态、发布与恢复

`gura_m1` schema v1 仅存数据集/权限、Snapshot 定义与 run、发布指针、pin 和 job 元数据，不存业务逐行数据。数据集 ID/租户/name/定义注册后不可变；定义冻结 root/key/text 字段。Snapshot 目标另固定 metadata/features URI、摘要与快照 ID。run 按 `(dataset,operation)` 幂等对账；同 operation 不同目标拒绝。新尝试递增 generation，旧 worker 即使晚完成也不能发布。

状态为 building → ready → published；失败为 failed。ready 只在完整数据与两路索引都创建并验证后写入。publish 再验证产物，在同一 PG 事务中检查 generation、expected epoch，改变 run 状态和 published 指针。失去发布响应先按 run/operation 查目录，已发布同一 run 返回原 epoch；不重放源提交，因为本服务没有源写。单路失败、取消、发布事务中断保留旧完整视图。新构建失败后旧 ready generation 被 fencing，需新 operation 重建，不能悄悄复活旧任务。

首次迁移是显式 init 到独立 schema v1，不覆盖既有业务 schema。没有 v0/v2 自动迁移或 downgrade。构建中进程崩溃可能留下 building 与部分目录；相同 operation 的重试遇到既有目录会失败并记录 failed，先查 run，再以新 operation 重建；不宣称透明断点续建。PG 重启保留指针、epoch、权限与 run；查询进程重启把遗留 queued/running 标为 worker_restarted 失败并释放其 job pin，保留已成功的持久结果及训练 pin。

单个服务进程持有 PG session advisory lock；第二个实例拒绝。连接失效不能自动重获旧 lease 继续工作，旧 worker 不能覆盖恢复终态。结果持久化出错且失败也无法记入目录时，服务 health 失败，需恢复数据库并重启对账。此切片无 HA/透明查询恢复。

## 固定视图、授权和保留

新请求在 PG 事务内同时选择当前 published run 并创建 pin。显式 read_view_id 可选同数据集未退休的已发布历史视图；不存在/retiring 不回退最新。句柄与结果始终绑定同一个 revision、实际源快照/metadata/features 版本、索引 generation。新版本发布不会改变已接受查询或导出。

HTTP token 哈希、租户、主体与 dataset grant 位于 PG。每次请求、状态/结果/Parquet/媒体下载、排队后的执行点及结果发布点重新授权；跨主体隐藏句柄。operator CLI 使用受保护 DSN，属于可信控制面入口，不接受用户 HTTP 中的租户身份。无行列策略，也不追回已返回字节。

构建将**所选快照**的 metadata、manifest list、manifest、Parquet、features 和被引用媒体字节逐个复制并固定哈希，M1 bundle 为 managed-copy。未选择的历史依赖不在该闭包内；不能延长外部快照生命周期。M0 兼容 manifest 仍沿用其 best-effort v1 字段，不把它当作 M1 的保留控制面。训练 manifest 指向逻辑对象摘要，授权下载路径为 `/v1/jobs/<id>/objects/<sha256>`；没有外部签名 URL 或凭据泄漏。样本 split 为 SHA-256(canonical JSON(seed,identity)) 前 8 字节无符号数 mod 10000，低于 train_basis_points 为 train，其余 validation。逻辑键排序和固定元数据使同视图/seed 的导出可复核。

查询 pin 在结果持久化/失败终态后释放；成功训练导出保留 job pin，直到显式 release。手工、job、临时 query pin 分开命名空间，重启不能删手工/训练 pin。GC 事务锁定 run、确认不是当前 published、没有任何 pin，标 retiring 拒绝新 pin，再只清理该生成 run 目录并标 retired；中断后可继续 retiring。没有源湖 GC，也没有 PG 行历史清理。查询的完整结果是独立持久产物，保留后可在源 run 退休后继续取数；训练 pin 在释放前保护媒体/源副本。

## 冻结资源边界

单个 metadata/Avro/feature/media默认对象限 4MiB，data 单对象32MiB；所有源读取合计32MiB、最多128次。最多32个 data file、64字段、10000行；单个Avro文件最多4096条。总 Arrow nbytes/声明解码检查64MiB；Tantivy writer 16MB 单线程。bundle 单文件32MiB，读取验证完整依赖/事实/索引累计128MiB、最多256次。服务2个执行线程、32个在途槽、16个HTTP连接，自提交起（含排队）的10秒应用作业 deadline；普通结果2MiB、单次下载32MiB。源构建30秒应用预算。

PG 最多16数据集、128 Snapshot run、128持久 job；达到 job 上限需 release 终态 job，CLI输出保留 query_id。手工 pin 上限1024；这些是 alpha 操作预算，非多租户硬隔离保证。JSON/Avro/Parquet/Tantivy 的同步库调用不能任意 CPU 抢占；库临时分配、OS缓存和Python对象额外计入实测RSS。只接受操作者控制的源，不宣称不可信文件沙箱。

性能冻结8192行、2数据文件、2维，记录构建耗时、源 GET/字节、5次cold-process/warm-process 延迟、artifact请求/字节与RSS，精确 top-10 必须与独立真值一致。冷进程不是冷磁盘/冷对象缓存，不据此声称生产SLO。另以相同8192行负载并测后台重建、检索与训练；完整performance/stability/soak仍未完成。
