# M0 实施与验收计划

状态：进行中。Task `m0-parquet-http`，基点 `5596117798126153a7ed9cfef291824ff8096925`，checkpoint 见 task-status。工作区开始干净，main，原始用户改动为无。详细设计见 [M0 合同](../design/m0-parquet-http.md)。

## 切片

1. 先冻结详细设计、SQL/类型/manifest/预算与失败合同，验证官方依赖组合、固定 toolchain/锁文件。
2. common/storage/catalog/connectors 实现清单校验、固定对象及 Parquet 受限读取；query 实现 AST白名单和 DataFusion。
3. gateway 实现只读异步 HTTP、权限/状态/固定分页/取消/限额；同步 OpenAPI 与可执行示例。
4. 独立 PyArrow/PG18/SeaweedFS 3.97 真值、组件性能和真实故障 driver；接入 ready suites 与 CI。
5. 单独审查后运行完整任务门禁，切片提交；提交后按原始 base 再检查，task-finish 归档并建 checkpoint。此任务不包含再次推送授权。

## 风险与 INV

INV-001/002 固定视图与身份；INV-007 授权撤销/游标；INV-008 字节/内存/取消/超时；INV-010 格式不支持拒绝；INV-012 PG子集/只读。原子业务写入、GC、索引发布、分布式/训练/ANN不适用，未实现能力保持缺口。涉及 common/storage/catalog/connectors/query/gateway，计划要求 rust/functional/performance-smoke/stability-component 及已有 bootstrap suites。

## 验证与恢复

功能使用 PyArrow 和真实 PG18 对照，覆盖正常/NULL/大整数与负向查询，不以同一 AST 实现产生真值；S3认证限固定 SeaweedFS 3.97 测试版本。性能预算在设计中预冻结，初始基线不做自比较；真实故障记录输入/seed、注入与恢复断言。缺少工具/driver不跳过，不删除原有测试；同一错误两次无新证据后定位根因。

开发环境无现成 Rust，Docker可用；优先官方固定Rust容器，宿主工具安装仅作备选。若环境或依赖阻断，保留日志和当前假设，恢复点不变。无业务数据副作用，临时容器/对象/凭据均由本任务创建与清理。

## 结果与复核

逐步记录实际支持、命令、局限和证据位置；最终依当前提交的 harness 报告，不能用文档/fixture工具测试冒充运行时验证或 M4 release。

已完成详细设计与6个crate、HTTP/manifest合同、固定Docker构建、真实验收driver及CI接线。实现后的[单独复核](../reviews/2026-10-17-m0-implementation.md)记录了null语义、执行点撤权等修正。初轮功能/性能/故障通过，最终执行pre-commit、提交后整项check、task-finish；精确报告和checkpoint以harness任务receipt为准，不在提交文档中伪造未来commit。
