# Git 接入变更计划与恢复点

状态：实现已完成，当前检查结果以对应 checkout 的 harness 报告为准。

## 范围与基点

用户要求开发可追溯、阻断错误可回滚，并指定本仓库作者为 `yizhouxw <yizhou.xw@gmail.com>`。开始时没有任何提交；先在仓库/契约/harness 49 项测试通过后建立首个基线，恢复 tag 为 `checkpoints/initial-baseline`。本次工具集成是其后的独立提交，未改数据库格式或产品边界。

## 风险与不变量

`plan` 对脚本与 harness 测试选择 repository/policy/contracts/harness-tests，没有运行时代码。不能自动提交已有用户改动、覆盖自定义 hooksPath、伪造质量证据或让回滚破坏失败现场；代码恢复不能声称撤销外部副作用。当前无远端或异地备份，不触发 push。

## 切片与恢复

先保存项目基线；新增 git-status/checkpoint/recover/install-git-hooks；pre-commit 在门禁前后核对提交索引与工作区并确认 HEAD 未变；同步工作流/AGENTS/ADR；定向测试后再单独复核，再由真实 pre-commit 提交。遇阻断保留现场，使用 initial-baseline 新建 detached 恢复目录，不执行 reset/clean。

## 验证合同

临时真实 Git 仓库覆盖 dirty/unborn/非法 ref、证据不匹配、恢复且保留当前文件、拒绝目标覆盖和自定义 hook 保护；本仓库实际安装并验证 hook 拒绝未暂存文件，随后通过 staged 快照门禁提交。功能测试包含已有全部契约/harness 测试。性能/数据库稳定性不适用：本次为开发工具，无数据库运行路径，不改变测量阈值或完整发布门禁。

## 复核和证据

独立于实现再复核 Git argv/ref/路径处理、dirty 状态保护、提交索引与工作区一致性、报告绑定与 hook 安装；增加检查后的索引/HEAD 再验证，防止检查期间换提交基点。复核还发现恢复不应依赖损坏的 policy，已移除该依赖并增加真实恢复 CLI 测试；提交后检查显式保留任务 base，避免空差异漏掉运行门禁。结果记录在 artifacts/harness，最终回复给出实际提交与检查点。证据不提交进源码，tag 保存摘要和 scope。

首次真实提交被门禁拦截：Git hook 继承的 `GIT_INDEX_FILE=.git/index` 在新 worktree 的 `.git` 为文件时导致 checkout 失败。恢复操作现清除 Git 公布的仓库局部环境变量，并显式注入该环境回归测试；未绕过 hook 或移除测试。
