# 开发指南

后续新能力或可观察行为修复，先写用户文档，再实现，最后按文档场景验证。设计方案与 ADR 解释取舍，用户文档解释用户如何使用、预期结果和失败边界；两者均需维护。

## 开发顺序

1. 阅读[功能白名单](features.md)、对应模块 AGENTS、相关契约/ADR 与[工程流程](../../harness/development-workflow.md)。检查 Git 和 active task，保留其它用户改动；非小型任务在干净基点 task-start，不覆盖已有任务。
2. **在修改行为代码前**更新 docs/user 的相关页面，将新增部分标为“规划/待实现”。写明用户场景、环境、输入/命令、结果、错误与拒绝范围、权限、预算、兼容/迁移/回滚。纯内部变更说明对用户行为无影响的依据；只改错字可轻量处理。
3. 在[变更计划](../../harness/templates/change-plan.md)关联文档路径、验收案例和验证命令；对照[场景模板](../../harness/templates/user-scenario.md)先冻结成功及负例。运行 plan，涉及接口同步版本化契约、示例和能力清单。
4. 先保留失败复现/独立真值，再做最小实现。新能力在验证前不能写成“已支持”；不降低预算、删负例或关闭 hook 获得通过。
5. 按文档逐步执行示例和拒绝场景，再运行适用功能/组件性能/故障与完整 change 门禁。记录真实输出、commit/checkout 指纹和报告。仅链接检查不能证明命令、权限或恢复语义。
6. 单独复核文档与行为一致性、失败和兼容边界，补齐证据后将已验证条目标记为当前有界实现。缺失工具/失败/超时必须保留为未验证或阻断。通过后按仓库流程选择性提交、提交后重验并 checkpoint/task-finish；推送需另行授权。

文档可与实现在同一最终提交，但计划/复核需记录先写合同的证据（先行文档提交或实现前 diff/任务记录）。目前没有自动证明编辑时序的门禁；这一顺序由开发者执行、复核人核对。必备页和链接由 repository suite 检查，真实功能由独立 driver 证明。

## 环境与验证

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock -r requirements-m0.lock -r requirements-m1.lock
.venv/bin/python scripts/harness.py install-git-hooks
.venv/bin/python scripts/harness.py plan
.venv/bin/python scripts/harness.py check
```

纯文档可先运行 `.venv/bin/python scripts/check_repository.py`；它只验证必备文件、链接与基础 JSON/API，不取代 change 门禁或数据库质量验证。当前对全部生产源统计单元行覆盖，适用行要求100%；Rust精确排除按[ADR 0015](../decisions/0015-unit-coverage-and-dual-interface-scenarios.md)审查并同时报告原始值，未豁免缺口仍阻断。对应命令映射见[验证页](validation.md)。

## 代码和交付约束

模块归属与依赖按[harness 架构清单](../../harness/architecture.toml)，源文件不超过 600 行。公共类型不反向依赖上层，不在客户端另造服务端语义。新增依赖固定版本与锁，写清用途/许可/兼容；持久格式变更先说明旧 reader/writer、作业/pin、升级和恢复。

默认在 main 完成普通任务；已有用户改动不能自动 stage/stash，不能绕过 hook 提交。长任务恢复先读 task-status、当前 diff/计划/最新失败。两次无新证据失败后定位根因，不能盲目重复；交接需留下已完成、失败现场、下一步和未解决风险。详细规则见[贡献指南](../../CONTRIBUTING.md)。
