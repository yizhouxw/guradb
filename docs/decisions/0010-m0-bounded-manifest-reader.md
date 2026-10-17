# ADR 0010：M0 有界 manifest 读取服务

- 状态：接受，限定 M0 内部 alpha
- 日期：2026-10-17
- 前置：ADR 0002 / 0003 / 0007，路线图 M0

## 决定

M0 先将受控、SHA-256 固定的 Parquet manifest 转为经过完整对象校验的 Arrow 批次，再使用 DataFusion DataFrame API 执行单表 SELECT 白名单。Rust 1.90.0 + DataFusion 50.3.0 + Arrow/Parquet 56.2.x 联编由锁文件、实际构建和测试证明。用户 SQL 经 PostgreSQL dialect AST 转换，不直接交给引擎执行，不开放文件发现或函数。

S3 首个验证后端为 SeaweedFS 3.97（固定镜像摘要），覆盖有/无version_id精确读取、历史版本和覆盖/缺失错误。local 后端只作受信任开发对照。此选择替代最初计划的 MinIO 验收环境：本机 Docker Hub 拉取被拒、quay返回401，因此换用真实可运行S3实现；不减少固定版本/错误语义断言，也不宣称未测S3服务兼容。

默认固定视图、身份/数据集allowlist、执行点重新授权、状态/取消、HMAC分页和资源预算在首个服务落实。句柄与结果保存在有界内存，终态TTL清理；重启恢复数据视图而旧查询失效。完整设计、限制和测试分别在 [M0 详细设计](../design/m0-parquet-http.md)、[运行说明](../design/m0-running.md)、[验收映射](../design/m0-validation.md)。

## 理由与代价

有界全扫描将正确性和接口闭环落到可审查的范围；牺牲范围读取/裁剪、缓存与大数据规模，不把“对象存储架构”误解为本切片已能处理海量数据。每查询扫描32MiB/解码64MiB，有限引擎内存且不spill。后续流式provider、范围读取和分布式可以沿用固定清单/视图合同，须重新证明功能和资源。

这不是硬RSS隔离或不可信文件沙箱，也没有索引、Iceberg、托管业务写、持久作业和多节点。M0不修改后续M1–M4范围。真实组件功能/性能/故障gate启用，完整performance/stability/soak仍planned，release不能通过。首次实测只建立组件smoke候选，无旧基线不得自比较。

## 验证与恢复

固定镜像/工具链/依赖，真实HTTP服务对照PyArrow与PostgreSQL18；使用真实S3版本读取及故障注入。任务原始基点、检查点、计划、pre-commit和提交后check由harness保存，最终task-finish归档并建可恢复tag。此切片无业务写入/数据迁移；代码恢复仍不能追回已返回的数据或外部源保留状态。
