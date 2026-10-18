# Git 追溯、检查点与恢复

状态：已接入本地 Git/harness 和私有远端；推送另行授权，异地备份未验证。

## 日常开发

1. 开始/恢复任务先执行 `git status --short --branch` 和 `harness.py git-status`，记录起始 commit、分支、现有改动和检查点。已有未提交的用户改动先保持原样，辨明归属并避免混入任务；不自动 stage、stash、reset 或覆盖。
2. 当前项目按单人开发，普通任务默认直接在 `main` 开发；已有工作分支完成后合回 `main`。干净基点创建 checkpoint，非小型任务记录目标、验证与恢复步骤。只有并行开发同一大需求时才引入多分支，每个分支使用独立 worktree，例如 `git worktree add -b codex/<slice> <new-directory> <base>`；不在同一工作目录切换多个开发分支，不强行切换有改动的工作区。
3. 完成有限切片，运行 plan/check，审查 `git diff`；只 stage 本任务文件，检查 `git diff --cached --check` 及 staged 差异，提交具体变更和验证说明。未完成/失败实验保留现场与日志，不当成质量合格基点；并行任务已有分支时可保存明确标记的 WIP 提交，未经门禁不得合入主线。
4. 提交后执行 `harness.py check --base <任务起始commit>`，使报告精确绑定新 commit/checkout 指纹，且仍覆盖整项任务差异；不能省略 base 后只检查空差异。再用 `harness.py checkpoint --label <label> --report <report.json>` 建立带证据的检查点。报告中的 scope 只是实际运行范围，bootstrap/change 不能冒充数据库 release。
5. 已有工作分支完成后，将通过门禁和复核的代码合入干净的 `main`；能快进时使用 `git merge --ff-only <branch>`，历史已分叉时保留历史并正常合并，冲突先分析再解决。合并后从合并前的 `main` 基点检查完整范围，生成绑定主线最终 commit 的报告和 checkpoint；不能只验证新增文档或空差异。普通任务在 `main` 完成同样闭环。
6. 结束报告起始/最终 `main` commit、检查点、实际验证和剩余改动。常规本地提交及完成后的合入 `main` 属于开发闭环；推送与远端设置仍另行授权。不强推、重写共享历史或自动删除旧分支/检查点。

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

命令只解析显式 checkpoint tag，创建 detached worktree，拒绝已存在或位于当前 checkout 内的目的路径。进入恢复目录后按其版本安装依赖，再运行检查；恢复目录用于保留和验证现场。恢复后的修复按上述单人/并行约定整合到 `main`，不把新分支设为所有恢复工作的默认前置条件。旧版本可能没有新 harness 命令，应使用该版本自己的检查入口。Git worktree 共享同一个对象库，**不是异地备份**。

恢复命令不加载当前 policy，策略损坏仍可恢复。若 Python 工具本身已损坏，先用 `git tag --list 'checkpoints/*'` 确认恢复点，再使用原生 `git worktree add --detach <全新外部目录> refs/tags/<checkpoint>`；不要在原目录强制覆盖。

若需要让当前主线撤销一个已提交的错误改动：先保留现场并建恢复点，确认提交范围，在干净树执行 `git revert <bad-commit>`，产生新的撤销提交，执行门禁与复核；冲突停止并诊断，不用 reset 强行解决。多提交、merge、迁移或依赖版本回滚必须给出具体顺序/补偿计划，不自动批量 revert。禁止 `reset --hard`、`clean -fd`、强制 checkout 或 force-push 作为 agent 默认恢复动作。

## 初始状态与备份边界

项目基线已保存为本地首个提交和 `checkpoints/initial-baseline`。按用户指定，仅本仓库配置作者 `yizhouxw <yizhou.xw@gmail.com>`，不修改全局配置；后续提交沿用该身份。

当前已配置私有远端；本地 commit/tag 能应对错误修改，不能应对磁盘损坏。推送分支/检查点仍需授权，远端必需 CI 与异地可恢复性须分别验证；也可把 `git bundle create <outside-repo>/guradb.bundle --all` 产物复制到独立存储并用 `git bundle verify` 验证。bundle 不含未提交文件或 artifacts 日志，数据/凭证也不应通过代码备份保存。
