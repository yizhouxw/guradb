# ADR 0005：Agent Harness 与质量门禁

- 状态：已采用的工程约定（用户要求初始化；当前仅 harness 层已实现）
- 日期：2026-10-17
- 关联：[架构](../architecture.md)、[harness](../../harness/README.md)

## 背景

项目将逐步扩大代码规模，质量不能只依赖 agent 提示、功能测试数量或开发者记忆。湖、索引、分布式与 AI 检索同时引入正确性、召回、I/O/资源和恢复风险，需可执行且能识别缺口的质量闭环。

## 决定

1. 根/模块 AGENTS 提供上下文和职责，机器 policy/架构 DAG、不变量、workload/fault registry 与统一 CLI 执行约束。
2. 按实际 Git 变更提升门禁；功能、性能与稳定性分别验收，生产源必须有归属，Cargo 路径依赖不允许反向/循环。
3. 当前执行仓库、OpenAPI 契约、policy 和 harness 自测。真实运行时 suites 保持 planned；需要时缺失就失败，不能把无内核的检查当发布合格。
4. 性能比较固定输入/环境，质量与成本不省略；高噪声/不可比较不记通过。故障证据保留 seed、注入、workers、不变量结果和 trace。
5. 独立 run 日志固定 commit/checkout 指纹，检查中代码变化使证据失效。CI 调用同一命令并保留失败产物。
6. 逐步启用真实 driver、长稳和升级/恢复验证，不引入假数据库或预填虚假 baseline。harness 自测不代替产品测试。
7. 首次组件与完整发布门禁分层依 [ADR 0007](0007-incremental-delivery-and-gates.md)：普通内核变更执行真实功能/组件性能/组件故障测试，完整 driver 变更与发布仍要求完整基准/故障 registry，发布另需 soak。planned/missing 不因分层变绿。

## 取舍与限制

工具使用 Python 标准库承载 policy/执行/证据处理，仅标准 OpenAPI 契约使用锁定开发依赖；不因此改变 Rust 推荐内核栈。代码行数与依赖图只是结构约束，不等价于代码质量或性能证明。

证据校验不证明报告诚实或 trace 语义，仍需真实 driver 与独立审查。仓库可修改自己的门禁，建立远端后需必需检查/合并权限配合；本轮无远端规则配置，不能声称已阻止所有绕过。

## 验证

harness 测试覆盖真实 Git 临时仓库、重命名/未跟踪、初次 push、Cargo workspace/别名/dev/build/target 依赖、超时/子进程清理、缺失 suite、运行中源码变化、性能质量/噪声/上下文和故障证据拒绝。具体结果以本次 run 报告为准。
