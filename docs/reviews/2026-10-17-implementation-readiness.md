# 产品设计复审与实施修正

状态：设计与契约修正已完成；实际检查状态以当前 checkout 对应的 harness 报告为准。这是设计与 harness 审查，不是数据库能力验证。

## 范围与依据

用户要求再次审查产品设计，使实施路径顺畅。保留分布式多模态、对象存储湖、PostgreSQL 语法方向、SQL/HTTP 和湖同步服务化目标，以及不承接高并发 OLTP/实时敏感事务的边界。

本次由产品、技术架构、接口/门禁三个独立审查方向检查现有文档。发现以下阻碍，并在对应契约中修正：

| 问题 | 影响 | 修正位置 |
| --- | --- | --- |
| P0 和前置 POC 同时要求全部格式、检索、同步和多节点 | 第一条链路依赖整库实现，POC 后又重复建设 | [路线图](../roadmap.md)、[功能架构](../product/functional-architecture.md)、[ADR 0007](../decisions/0007-incremental-delivery-and-gates.md) |
| 没有冻结外部记录身份、空键/重复键与版本规则 | 索引去重、回表和增量可能覆盖或漏数据 | [数据合同](../product/data-contracts.md) |
| 多表提交与发布 CAS 混淆，未对账提交会进入下一写入基线 | 失败作业的部分写入可能被后续视图带出 | [架构](../architecture.md)、[ADR 0004](../decisions/0004-snapshot-and-index-publication.md) |
| 查询重解源最新、摘要代替保留、本地 pin 冒充源保留锁 | 混用版本或无法兑现历史复现 | [格式矩阵](../compatibility/lake-formats.md)、[同步目标](../product/lake-sync-and-serving.md) |
| 只读/批写契约混合，结果允许完全不披露视图 | 首个查询接口和未来写入对账都缺乏明确边界 | [接口](../interfaces/query-and-clients.md)、[OpenAPI](../../api/http/openapi.json) |
| 第一份运行时代码必须通过整库基准和全部分布式故障 | 最小组件无法接入门禁 | [质量模型](../../harness/quality-model.md)、[首次内核接入](../../harness/runtime-onboarding.md) |

## 风险、不变量与变更计划

本次没有数据库运行实现或持久数据迁移。文档统一里程碑、身份、源版本、提交/发布、保留与回收义务；这些仍需对应切片的真实实现和故障验证。

源提交与本地发布分离的风险推演，依据 Iceberg 冲突重试会基于新表状态重建提交的行为；旧字节可取性和源快照保留也分别核对了官方资料。[Iceberg Reliability](https://iceberg.apache.org/docs/latest/reliability/)、[Iceberg Maintenance](https://iceberg.apache.org/docs/latest/maintenance/)、[S3 Versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html)。

门禁变更前，`plan --path modules/storage/src/cache.rs --path Cargo.toml` 要求整库 `performance/stability`，即使 `runtime_present=false`。修改后普通内核变更仍需 `rust/functional`，性能与稳定性分别选择真实的组件 smoke/故障套件；完整基准、完整 fault registry 与 soak 仍是发布必需项。当前无真实 driver，新组件套件继续 planned/missing，不能把本轮自测当作新增数据库覆盖。

实施步骤：冻结里程碑和首条源/变化白名单；补齐数据合同与一致性边界；收敛只读 HTTP 契约及负例；修正门禁分层并增加选择/拒绝回归测试；独立复核后执行当前仓库检查。

## 验证合同

- 功能：当前 OpenAPI 标准与正反例；harness suite 选择、组件路径不误升级、缺失组件套件仍失败、发布仍要求整库验证。
- 性能/稳定性：本轮不改变测量比较器、阈值、完整 workload/fault registry 或已有实测产品基线（当前不存在）；只修复未实现组件的接入层级。数据库实验在各里程碑另行执行。
- 文档：本地链接、状态声明、里程碑范围、单表写/源版本/保留语义一致。未实测的 PG、格式、ANN、Graph、分布式能力不写成已支持。

## 结果与审查

执行结果和剩余限制见本轮最终报告；检查器在 `artifacts/harness/` 保存带 checkout 指纹的独立报告。这里不写入该次报告的自身路径，避免记录更新反过来使指纹失效。

修正后另做独立交叉审查：组件/完整门禁选择与 planned 阻断未发现剩余死锁；身份/版本/保留合同可按切片实现。复核提出的“两类客户端同时成为 alpha 前置”和“外部特征接入隐含依赖 writer”已修正：M1 以 HTTP 和一个薄适配验收，特征注册源列或不可变清单，完整 CLI/MCP 在 M3 集成。

剩余待验证项是实际内核依赖、源格式特性、PG 白名单、性能绝对预算和真实故障/长稳证据，分别在对应切片开始前冻结并实现；本轮没有将它们判定为通过。
