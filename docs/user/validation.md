# 手册验证与场景映射

手册于2026-10-19从alpha操作说明扩展为产品指南主干。完整产品流程仍待实现；下表是既有alpha的复现入口和验收要求，**不是本轮已通过清单**。产品目标与当前操作按页标注。

| 场景 | 用户验收断言 | 正向/负向验证入口 |
| --- | --- | --- |
| U01 安装与 SQL | fixture→构建→HTTP 查询，id > 2 且升序、最多 5 行；错误 token 拒绝；JOIN 拒绝 | [安装页](installation.md)；`scripts/m0.py functional`、`tests/functional/interface_scenarios.py` |
| U02 PG SDK | loopback、autocommit、绑定参数；认证、事务/目录语法拒绝 | [PG 指南](../design/pg-wire-running.md)；`tests/functional/pgwire.py`、`tests/functional/pgwire_protocol.py` |
| U03 快照与检索 | 构建后 CAS 发布、固定 read_context、独立检索真值；权限/模型/维数错误拒绝 | [使用页](usage.md)；`scripts/m1_acceptance.py functional`、`scripts/m2_acceptance.py functional` |
| U04 训练与保留 | 固定视图全记录、确定性 split、下载、pin、release 后不可取 | [使用页](usage.md)；`tests/functional/m1.py`、`tests/contracts/test_capabilities.py` |
| U05 刷新与 Graph | append 继承版本、一跳预算；update/delete/rewrite/多跳拒绝 | [M2 操作](../design/m2-running.md)；`tests/contracts/test_incremental.py`、`tests/contracts/test_graph.py`、`tests/functional/graph.py` |
| U06 运维恢复 | 冻结后联合备份、新目录/空 PG 恢复、权限对账、事实完整才重建 | [运维页](operations.md)；`scripts/local_acceptance.py recovery`、`inspection`、`rebuild` |
| U07 worker | 同机三端点、共享 root；HMAC/owner/过期/越界/取消拒绝 | [HTTP worker](../design/local-worker-http.md)；`tests/contracts/test_transport.py`、`scripts/p0_acceptance.py --transport http` |
| U08 文档与开发 | 必备页、相对链接、契约；先行用户合同与案例在复核时可查 | `scripts/check_repository.py`、`scripts/harness.py check`；[场景表](../../harness/templates/user-scenario.md) |

## 产品旅程的新增验收责任

[产品合同](../product/product-contract.md)的J1–J6覆盖数据管理、多模态检索、SQL准备、训练、生命周期和部署恢复。对象/公共API、共同目录/查询、自有图文教程、实际训练reader、多机/生产等缺口均为待实现，不由上表U01–U08替代。

每条旅程需要完整前置/操作/预期、独立真值和负例、权限/预算、版本/迁移/恢复；完整手册责任见[建设合同](manual-plan.md)。新页不含虚构建库/上传/查询扩展语法，目标示例不可作为已运行证据。

## 本轮执行与证据规则

先做文档存在/链接检查，再按涉及的用户行为执行合成示例、成功/负例及对应门禁。结构检查不证明命令正确，--help 不证明服务启动，组件 smoke 不证明完整性能/稳定性；完整 release 仍缺 performance/stability/soak。

本次任务`product-direction-correction`仅改研究、方案与文档，无运行时、契约或依赖变化。门禁按任务原始base选择；独立研究/源码审计和最终只读复核记录见[方向复审](../reviews/2026-10-19-product-direction.md)。最终报告绑定本轮commit，不复用历史数据库性能/稳定性结果。

初始化时对运行说明、能力清单和实际入口做交叉复核；例如 CLI 用 `--url` 配置服务地址，而 MCP 使用 `GURADB_URL`，两者不能混用。示例中的 QUERY_ID/JOB_UUID/DATASET/RUN 和自有 snapshot/摘要需由实际输出或用户数据替换，手册不包含真实凭据。

## 历史初始化证据

- M0 安装示例已真实构建和启动，通过独立 PyArrow 对照得到预期 5 行，3 页 read_context 一致；错误 token 返回 401，JOIN 返回 400，容器正常清理。原始记录：`artifacts/user-docs/quickstart-f89a9c410e/result.json`。为保护现有服务，使用唯一目录/容器名及临时宿主 loopback 端口，其余参数和请求与安装页一致。
- 初始化时的文档/缺页负例和shell语法记录位于`artifacts/user-docs/`，它们不覆盖本轮新增内容，不能替代当前文档检查。
- 首轮 change 报告 `artifacts/harness/20261019T000051Z-39146695/report.json` **未通过**：恢复、M1 性能 smoke 及最终指纹检查检测到并发源码修改，证据失效；不作为当前版本通过依据。
- 初始化最终重验及复核在`artifacts/user-docs/harness-final.log`与`review.md`；此前`docs-test-coverage`任务已完成，是历史上下文，不是本轮active任务。

## 后续维护

每次行为变更按[开发指南](development.md)先更新对应页面和[场景表](../../harness/templates/user-scenario.md)，填写文档先行证据、实际结果、commit/checkout digest、配置/数据摘要和报告路径。测试失败或环境缺失保留 failed/missing；经过实测和复核才更新支持状态。初始化示例不能长期充当后续版本通过证据。
