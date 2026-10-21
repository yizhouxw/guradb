# 开发指南

后续新能力或可观察行为修复，先写用户文档，再实现，最后按文档场景验证。设计方案与 ADR 解释取舍，用户文档解释用户如何使用、预期结果和失败边界；两者均需维护。

手册内容按[建设合同](manual-plan.md)区分概念、教程、任务、参考与管理员材料；开发者证据不放进普通入门流程。每片关联[产品旅程](../product/product-contract.md)，不能仅因模块或页面存在便判定产品完成。

## 开发顺序

1. 阅读[功能白名单](features.md)、对应模块 AGENTS、相关契约/ADR 与[工程流程](../../harness/development-workflow.md)。检查 Git 和 active task，保留其它用户改动；非小型任务在干净基点 task-start，不覆盖已有任务。
2. **在修改行为代码前**更新 docs/user 的相关页面，将新增部分标为“规划/待实现”。写明用户场景、环境、输入/命令、结果、错误与拒绝范围、权限、预算、兼容/迁移/回滚。纯内部变更说明对用户行为无影响的依据；只改错字可轻量处理。
3. 在[变更计划](../../harness/templates/change-plan.md)关联文档路径、验收案例和验证命令；对照[场景模板](../../harness/templates/user-scenario.md)先冻结成功及负例。运行 plan，涉及接口同步版本化契约、示例和能力清单。
4. 先保留失败复现/独立真值，再做最小实现。新能力在验证前不能写成“已支持”；不降低预算、删负例或关闭 hook 获得通过。
5. 按文档逐步执行示例和拒绝场景，再运行适用模块功能/组件性能/故障与该层级 change 门禁。记录真实输出、commit/checkout 指纹和报告。仅链接检查不能证明命令、权限或恢复语义。
6. 单独复核文档与行为一致性、失败和兼容边界，补齐证据后将已验证条目标记为当前有界实现。缺失工具/失败/超时必须保留为未验证或阻断。通过后按仓库流程选择性提交、提交后重验并 checkpoint/task-finish；按用户授权将验证后的开发提交推送任务分支到现有 `origin` 并创建 PR，按 [PR 并行流程](../../harness/parallel-development.md) 验证后串行合入 `main`；不再逐次询问，不强推，远端设置与部署另行授权。

文档可与实现在同一最终提交，但计划/复核需记录先写合同的证据（先行文档提交或实现前 diff/任务记录）。目前没有自动证明编辑时序的门禁；这一顺序由开发者执行、复核人核对。必备页和链接由 repository suite 检查，真实功能由独立 driver 证明。

## 环境与验证

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock -r requirements-m0.lock -r requirements-m1.lock
.venv/bin/python scripts/harness.py install-git-hooks
.venv/bin/python scripts/harness.py plan
.venv/bin/python scripts/harness.py check
```

纯文档可先运行 `.venv/bin/python scripts/check_repository.py`；它只验证必备文件、链接与基础 JSON/API，不取代 change 门禁或数据库质量验证。四层验证按[策略 v2](../plans/2026-10-21-modular-delivery-v2.md)实施；模块层统计完整 owner 的全部适用生产源，系统/发布层按其完整范围统计，适用行要求100%；Rust精确排除按[ADR 0015](../decisions/0015-unit-coverage-and-dual-interface-scenarios.md)审查并同时报告原始值，未豁免缺口仍阻断。对应命令映射见[验证页](validation.md)。

## 代码和交付约束

模块归属与依赖按[harness 架构清单](../../harness/architecture.toml)，源文件不超过 600 行。公共类型不反向依赖上层，不在客户端另造服务端语义。新增依赖固定版本与锁，写清用途/许可/兼容；持久格式变更先说明旧 reader/writer、作业/pin、升级和恢复。

所有任务默认使用独立分支/worktree，经 PR 合入 main；已有用户改动不能自动 stage/stash，不能绕过 hook 提交。长任务恢复先读 task-status、当前 diff/计划/最新失败。两次无新证据失败后定位根因，不能盲目重复；交接需留下已完成、失败现场、下一步和未解决风险。详细规则见[贡献指南](../../CONTRIBUTING.md)。

## 共同读合同开发验证（离线模块验收）

P00 CF1-A提供离线的版本化共同读合同、schema/golden与Python/Rust互通验证。它供各模块开发者传递固定dataset/revision/view、授权/pin/预算及对象/批次，不新增数据库命令或用户入口。合同版本、显式int8/NULL编码、严格拒绝及登记/发布未知结果边界见[CF1-A合同](../interfaces/cf1a-contract.md)，执行映射见[场景表](../design/cf1a-scenarios.md)。真实PG/对象/源、取消预算执行及共同查询仍待独立集成；CF1-B/C待后续冻结。

本地已用真实Rust进程与Python双向交换12组golden并核对23种拒绝code，修复后的完整10项门禁通过。执行命令、报告和覆盖率见[变更计划](../design/cf1a-change-plan.md)；最终commit绑定的harness报告由task receipt归档，互通原始JSON/log/manifest另行复制到共同Git归档并在receipt的review中引用。PR CI、真实后端接线与I1仍待独立验收。

## 模块到用户结果的交接

先按[需求矩阵](../product/requirements-v2.md)确认具体功能 ID、唯一 owner、正负案例与预算，再按[模块合同](../design/module-delivery-contracts.md)开发。模块自身 PG/S3/Arrow 等依赖真实验证，外部模块可用固定版本替身；模块结果必须标清替身边界。稳定点立即登记真实生产者/消费者配对，之后进入系统集成批次。运行报告区分 module/pair/system/release，不能用组件报告宣称用户闭环或发布通过。

门禁实现由 gates-v2 接入 CLI/pre-commit/CI；新层级代码尚未合入前原命令仍按旧语义执行，不能只改参数文字绕过原门禁。工程工具变更需自测、选择差异、防伪负例与独审，不改变数据库预算或跳过 planned 发布套件。此工作流调整不新增数据库 API、持久布局或 SQL 语法。
