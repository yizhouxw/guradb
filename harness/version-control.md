# Git 追溯、检查点与恢复

状态：已接入本地 Git/harness 和私有远端；用户已授权验证后的任务分支推送与 PR 合入；异地可恢复性仍需独立验证。

## 日常开发

1. 开始/恢复任务先执行 `git status --short --branch` 和 `harness.py git-status`，记录起始 commit、分支、现有改动和检查点。已有未提交的用户改动先保持原样，辨明归属并避免混入任务；不自动 stage、stash、reset 或覆盖。
2. 所有开发任务默认从核对后的 `origin/main`（合同冻结任务可记录显式已提交基点）创建 `codex/<task>` 分支与独立 worktree，不在 dirty 工作区切分支。按 [GitHub PR 并行流程](parallel-development.md) 划定 owner、依赖和文件范围；不直接向 main 提交/推送。开始时创建 checkpoint，非小型任务 task-start 固定原始 base。
3. 有限切片运行 plan/check 并单独复核，只 stage 本任务文件，检查 staged diff 后提交；禁止绕过 hook。未经门禁的 WIP 只能保留在任务分支，不得合入主线。
4. 提交后对任务原始 base 执行 `harness.py check --base <task-base>`，报告须绑定当前 commit/checkout；完成分支任务时 task-finish 归档并创建 checkpoint。更新分支后旧报告失效，重新验证；原始 base 不得随同步主线缩短。
5. fetch 核对远端后正常推送任务分支，在 GitHub 创建以 main 为目标的 PR；复核与两个 PR quality job 通过、依赖已合入且当前分支包含最新主线后，由集成者使用 merge commit 串行合入。禁止本地 merge 后直接 push main 绕开 PR；具体操作和主线竞争处理见并行流程。
6. 合并后在独立干净 worktree 对合并前 main 到最终 merge commit 的完整范围运行 check，建立主线 checkpoint，核对主线 push CI；最终交付关联分支和主线两组证据。失败停止下一 PR，保留现场，通过修复或 revert PR 恢复。
7. 用户已授权验证后的任务分支推送、PR 创建与满足门禁后的 PR 合入，不再逐次询问。不得强推、覆盖远端新提交或自动删除旧分支/检查点；远端权限/保护设置、发布和部署仍需另行授权。结束报告基点/最终 commit、PR、报告、checkpoint 和剩余改动。

非小型任务由 [task-start/status/finish](development-workflow.md) 将原始 base 和完成证据持久化；本地 auto 检查沿用 active task 基点。`task-finish` 对 change/release 报告重算整项变更和门禁、校验日志并归档，再结束任务；不支持用 bootstrap 或提交后的空差异报告结项。

安装本仓库 hook（每个新 clone/工作环境显式执行；自定义 hooksPath 会保留并报错）：

```sh
.venv/bin/python scripts/harness.py install-git-hooks
.venv/bin/python scripts/harness.py git-status
.venv/bin/python scripts/harness.py checkpoint --label before-task
```

`pre-commit` 调用同一 change 门禁。存在未暂存/未跟踪文件时拒绝提交，防止“测试工作区 A、提交索引 B”；应选择性整理本任务文件或用 worktree 隔离，不能为过检查而提交别人的内容。缺失依赖/运行时 suites 仍阻断。hook 是本地协作约束，可被 Git 参数绕过；禁止 agent 使用 `--no-verify`、`HUSKY=0` 或禁用 hook 消除失败，远端必需检查仍需另配。

`checkpoint` 仅接受已有提交且无未提交文件的工作区，创建不覆盖旧名字的 annotated tag `checkpoints/<UTC>-<label>-<random>`；不自动提交。未给报告时 `quality=not_assessed`，它只是恢复点。给 `--report <report.json>` 时重新计算范围/门禁，校验全部命令、日志 SHA-256、本次 commit 与 checkout digest；tag 保存 scope、base、报告摘要及本地归档位置。报告和日志保存在共同 Git 管理目录 `guradb/evidence/`；只有头部 passed 的旧报告需重跑，不能补填为通过。校验不证明报告诚实，归档不是异地备份。

## 错误阻断后的恢复

先停止对外副作用和新写入，保留失败命令、日志、diff、基点与错误原因。代码恢复不会撤销已发生的数据提交、迁移、对象删除或外部 API 调用；这些必须按对应协议对账/恢复，禁止假定 `git revert` 能恢复业务数据。

默认恢复到**新目录**，当前 dirty 文件、分支与未跟踪文件保持原样：

```sh
.venv/bin/python scripts/harness.py recover \
  --checkpoint checkpoints/initial-baseline \
  --destination /absolute/new/path/guradb-recovery
```

命令只解析显式 checkpoint tag，创建 detached worktree，拒绝已存在或位于当前 checkout 内的目的路径。进入恢复目录后按其版本安装依赖，再运行检查；恢复目录用于保留和验证现场。恢复后的修复按上述 PR 并行约定整合到 `main`，仅验证恢复现场时可保持 detached；需要提交修复时从恢复点建立任务分支并走 PR。旧版本可能没有新 harness 命令，应使用该版本自己的检查入口。Git worktree 共享同一个对象库，**不是异地备份**。

恢复命令不加载当前 policy，策略损坏仍可恢复。若 Python 工具本身已损坏，先用 `git tag --list 'checkpoints/*'` 确认恢复点，再使用原生 `git worktree add --detach <全新外部目录> refs/tags/<checkpoint>`；不要在原目录强制覆盖。

若需要让当前主线撤销一个已提交的错误改动：先保留现场并建恢复点，确认提交范围，在干净树执行 `git revert <bad-commit>`，产生新的撤销提交，执行门禁与复核；冲突停止并诊断，不用 reset 强行解决。多提交、merge、迁移或依赖版本回滚必须给出具体顺序/补偿计划，不自动批量 revert。禁止 `reset --hard`、`clean -fd`、强制 checkout 或 force-push 作为 agent 默认恢复动作。

## 初始状态与备份边界

项目基线已保存为本地首个提交和 `checkpoints/initial-baseline`。按用户指定，仅本仓库配置作者 `yizhouxw <yizhou.xw@gmail.com>`，不修改全局配置；后续提交沿用该身份。

当前已配置私有远端；本地 commit/tag 能应对错误修改，不能应对磁盘损坏。用户已授权经验证的开发提交推送现有 `origin`；checkpoint tag 不随分支默认批量推送，远端设置和部署另行授权。远端必需 CI 与异地可恢复性须分别验证；也可把 `git bundle create <outside-repo>/guradb.bundle --all` 产物复制到独立存储并用 `git bundle verify` 验证。bundle 不含未提交文件或 artifacts 日志，数据/凭证也不应通过代码备份保存。
