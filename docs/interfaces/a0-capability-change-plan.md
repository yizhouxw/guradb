# A0 支持清单与接口状态对账

状态：本分支实现与独立复核完成；最终门禁和结项状态以本任务 receipt 为准。任务：`a0-capability-contract`，仅交付本分支，主线集成由独立会话完成。

起点：`d95d1ada607fe40a6b1cf8eb19773b3a10f95bae`，分支 `codex/a0-capability-contract`，工作区 `/Users/chad/.codex/worktrees/a0-capability-contract/guradb`，起始干净。恢复点：`checkpoints/20261018T102211Z-before-a0-capability-contract-9ec05918`。没有修改共享主目录。

## 用户可观察验收与范围

按[12域复审](../reviews/2026-10-18-capability-architecture.md)核对实际代码，交付可离线读取、带 schema 版本的统一支持清单，入口由接口、HTTP 和格式文档可发现。清单绑定所在源码版本，不能证明某个部署已启用能力；现有数据集 describe 继续报告实际 schema/model/read_context/retention_mode。

- M0 单表 SQL 与 M1/M2 scan/search/graph/export 分开；不把目标 SQL 融合语法列为已实现。
- 旧 bundle v1 Tantivy 与新 bundle v2 全局统计 BM25 分开；训练明确全固定视图，仅 seed/split 参数。
- 源 append 增量、索引全重建、内部 Lance 与外部连接器、单机操作者 writer 与本地三 worker 各有支持/拒绝边界。
- 清单字段、未知版本/状态、HTTP 请求白名单及关键运行时拒绝行为有正反例；证据入口可定位，不以路径存在冒充完整覆盖。

不实施 A1–A6，不增加训练筛选、公开写 API、格式/SQL/预算或多机能力。不改检索/训练/worker 算法，不改共同 driver、harness 或预算。

## 风险、不变量与兼容

依据 ADR 0010/0011/0012/0013 与 INV-001/003/007/008/010/011/012：本片风险是支持声明过度及发现内容漂移，运行时、身份/固定视图/授权/取消/发布协议保持原有行为。选择离线清单而非扩展 describe 响应，避免新授权或版本协商路径。

`plan` 对 api 路径选择 contracts、functional、harness-tests、performance-smoke、policy、repository、stability-component；affected_modules 为空、runtime_changed=false。遵守自动选择，不以文档性质跳过门禁。新增清单是版本化文档合同，消费者遇未知 schema_version/能力必须不推导支持。无持久格式、数据迁移或依赖升级；旧客户端响应不变，回退源码即可移除清单，但不撤销已执行作业或外部源变更。

## 验证与恢复边界

先运行新增轻量合同单测，再完整 check、独立复核、pre-commit、提交后覆盖原始 base 的 check 和 task-finish。所有重型门禁及 pre-commit 通过 Python fcntl.flock 持有共同 Git 管理目录 `guradb/coordination/a0-heavy-gates.lock`，覆盖整个命令与子进程。测试输出仅在本 worktree；不并发测量，不触及其他会话资源。

功能真值：清单12域与源码/现有合同交叉检查；训练使用手写预期全样本身份、版本、NULL/int8及极端split；请求正例和未知选择/写入/远端地址负例。已有 BM25/ANN/Graph/增量/writer 合同与真实组件门禁仍是实现证据，不新增性能支持声明。

沿用现有固定输入、质量与资源阈值；不调整10000行/32文件/256维/1000候选等预算，组件烟测不能称完整 baseline 或 release。无新故障面，仍运行被选组件故障。失败保留日志/diff，连续两次无新证据时定位根因；需要恢复时在新目录 recover 上述 checkpoint，业务数据与外部副作用单独对账。

## 结果与交接

最终命令、独立审查、精确 commit 报告和完成 checkpoint 由任务 receipt 与最终交接记录；本分支完成不代表整个 A0 或主线集成完成。不得推送、改远端或部署。

已新增12域离线清单和封闭版本 schema，两份 OpenAPI 通过 `x-guradb-capability-manifest` 指向同一清单；不新增 HTTP 响应字段。接口与格式文档区分实际支持、限制与历史目标。

局部执行 `.venv/bin/python -m unittest tests.contracts.test_capabilities`：8项通过；`scripts/check_repository.py`、`harness.py lint` 与 `git diff --check` 通过。独立只读复核检查实际代码、支持矩阵、版本/拒绝边界和正反例，发现一处 Parquet 上下文归属表述，已明确只有配套 manifest 保存 read_context/model/seed；复核无其他阻断项。独立复核没有运行门禁，也不把作者测试总结当验证证据。

限制：清单仅随源码版本解释，部署仍需实际授权/视图/索引检查；原有全量 rows/产物校验、全视图导出、本地部署和完整发布缺口保持。其他目录 README 的历史措辞、全局导航/行动计划收尾及主线合入交给集成会话，不在本片捎带修改。
