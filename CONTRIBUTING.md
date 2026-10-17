# 贡献指南

当前重点是建立一致的设计依据，再逐步实现可验证的能力。

## 开始工作

1. 阅读 [项目说明](README.md)、[架构](docs/architecture.md) 和相关模块说明。
2. 确定本次修改属于文档完善、待讨论提案，还是已接受方案的实现。
3. 对影响长期边界的选型，在 [ADR 目录](docs/decisions/README.md) 新增提案并解释备选方案与代价。
4. 按 [harness](harness/README.md) 运行 plan，更新文档、示例和契约，执行 `.venv/bin/python scripts/harness.py check`（或 `make check`）。

非小型需求按[开发流程](harness/development-workflow.md)先冻结验收/边界并 task-start，自动保留原始范围；依赖升级、持久迁移、失败定位与交接遵循同一规范。提交后重验并 task-finish 归档证据。小型文字修改可用轻量提交说明和显式 base。

## 文档约定

- 产品需求、技术建议与实现状态分别描述；计划中的能力必须明确标记。
- 文档采用仓库相对链接，引用外部标准优先链接官方规范，并注明重要版本限制。
- 一项能力至少说明使用场景、接口语义、数据与权限边界、失败行为和验收方式。
- API 变化同步修改 [OpenAPI 草案](api/http/openapi.json)、[接口说明](docs/interfaces/query-and-clients.md) 与 [HTTP 示例](examples/http/query.json)。
- 不提交访问令牌、真实用户数据、数据库文件、大型媒体或生成结果；测试样本优先使用小型合成数据。

## 代码与验证

模块说明定义责任归属，不要求一个模块对应一个进程。Rust 推荐 POC 栈见 ADR 0003，具体构建版本在联编后固定。生产源文件必须登记模块归属，Cargo 本地依赖遵守 harness 中的允许边与无环约束。

`make check` 运行实际变更所需门禁，`make check-docs` 才是基础文档检查。开发依赖使用 `requirements-dev.lock`；harness 执行报告放在 artifacts。后续测试按 [质量模型](harness/quality-model.md) 与 [测试规划](tests/README.md) 分层，文档改动无需编造内核测试。

高风险变更记录功能、性能/质量/成本、故障恢复和回滚证据，并单独复核。修改 baseline/门禁不能只为消除回归；缺失真实 driver 时保留 planned/missing 状态。接入步骤见 [runtime-onboarding](harness/runtime-onboarding.md)。

版本管理按 [Git 工作流](harness/version-control.md)：起始记录基点，有限切片提交，提交后报告绑定 commit 并建立 checkpoint；复杂实验/已有改动用独立 worktree。安装本仓库 pre-commit hook，禁止绕过失败。恢复默认在新目录检出 checkpoint，主线撤销用 revert 保留历史；代码恢复不替代数据恢复。私有远端已配置；新推送需明确授权。

提交说明应描述具体变化及验证方式。发布、项目许可证与贡献授权政策仍需单独确定，不能从骨架推断。
