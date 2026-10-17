# ADR 0008：Git 追溯与安全恢复

- 状态：已采用的工程约定；本地工具已接入，远端待配置
- 日期：2026-10-17
- 依据：用户要求版本管理接入 agent harness，使开发可追溯、阻断错误可回滚
- 规范：[Git 工作流](../../harness/version-control.md)

## 决定与取舍

使用已有 Git 仓库，建立首个项目基线与不可覆盖的 checkpoint tag。开发按有限切片提交，记录起始/最终 commit、质量报告与 checkout digest；分支/worktree 用于隔离复杂实验和已有用户改动。提交前 hook 运行同一 change 门禁，并拒绝未暂存/未跟踪的工作区，避免验证与提交内容不同。

`checkpoint` 只标记干净的已提交状态，证据匹配时在 annotated tag 中保存实际验证 scope 和摘要；不以恢复点名字代表产品质量。`recover` 在新目录建立 detached worktree，保留当前失败现场。当前分支撤销采用经复核的 revert 新提交，不重写历史。默认不执行破坏性 reset/clean，不自动推送。

本地 hook 可被绕过，tag/对象也可人为删除，不能冒充不可篡改审计或异地备份。远端保护与数据备份另行配置。代码回滚不撤销持久数据和外部副作用，恢复前必须对账并采用对应迁移/数据恢复方案。

## 验证

真实临时 Git 仓库测试覆盖 unborn/dirty 检查点拒绝、报告与 commit/指纹不匹配拒绝、恢复旧文件且保留当前 dirty/untracked 文件、拒绝覆盖目录、staged 快照检查和既有 hook 配置保护。实际本仓库安装 hook 并执行提交前门禁；当前仍无数据库内核。
