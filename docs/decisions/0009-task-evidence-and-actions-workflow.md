# ADR 0009：任务范围、完成证据与 GitHub Actions

- 状态：本次流程复审采用；本地工具已接入，Actions 待远端首跑，CD 待服务/环境
- 日期：2026-10-17
- 依据：用户要求完善开发流程，并询问以 GitHub Actions 实现 CI/CD
- 规范：[开发流程](../../harness/development-workflow.md)、[CI/CD](../../harness/ci-cd.md)

## 发现与决定

1. 只有手写基点易在多提交/上下文恢复后遗漏，任务采用每 worktree 的 start/status/finish/abandon receipt，保存 objective、branch、原始 base、检查点与结项复核。无显式 base 的本地检查沿用 active task；分支/base 异常拒绝静默继续。
2. 完成证据不能只看 passed 头部：按当前 policy 重算范围，验证 suites/commands、argv、退出码、日志摘要、HEAD 与 checkout。task-finish 只接受覆盖原始 base 的 change/release 报告，bootstrap/空范围不能代替任务验收。
3. 成功 checkpoint 归档报告、命令日志与路径映射到共同 Git 目录，保留摘要与实际 scope。它不是异地备份、不可篡改审计或 driver 真实性证明。
4. CI/CD 采用 GitHub Actions 分层；当前 CI 统一调用 harness，PR/push 按差异、手动默认全树，最小权限/固定 action SHA/失败证据上传，明确 Python 与总超时预算。普通 hosted runner 不充当真实性能基线环境。
5. CD 待真实构建物、环境、权限、健康/迁移恢复合同后接入，同一产物 digest 从 staging 晋升生产；现阶段不写假成功部署或声称外部配置已生效。
6. Definition of Ready/Done、依赖锁/兼容、有限重试根因定位、数据迁移与交接写入 harness，验证粒度仍按 ADR 0007，不削弱已有完整发布门禁。

## 验证与限制

真实 Git/临时命令测试覆盖多提交后保留基点、任务冲突/切分支拒绝、无关/缺失/篡改证据拒绝、policy 绑定、日志归档与独立 worktree 状态。CI 配置解析和预算/权限约束在本地测试；GitHub 首跑、远端保护和 CD 仍需真实环境验收。
