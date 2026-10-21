# GitHub PR 与多分支并行开发

状态：2026-10-20采用的工程流程，见 [ADR 0019](../docs/decisions/0019-pr-parallel-development.md)。本轮只改变协作合同、文档和 PR 模板，无数据库用户行为、API、持久布局或性能变化；不要求新增数据库场景测试。已有 Actions 仍执行同一 harness，不新增假成功门禁。远端保护未由本文件自动开启。

## 1. 验收、范围与角色

验收结果：贡献者能从固定基点建立隔离任务，按文件归属并行开发，提交可追溯证据，通过 PR 评审、两版本 CI、按依赖顺序合入主线，再验证最终合并 commit。普通文档任务也走 PR；不再直接提交或推送 main。支持独立任务和有依赖任务，拒绝共享 dirty 目录、未声明的跨 owner 修改、绕过检查合并和强推历史。

- 协调者在计划/Issue 中记录任务 ID、目标/非目标、可观察验收、owner、分支/worktree、起始 SHA/合同版本、允许文件域、依赖 PR、审查责任与集成顺序。小任务可直接写 PR；大型需求使用[变更计划](templates/change-plan.md)。
- 实现者独占一个任务分支/worktree，维护用户文档先行合同、task receipt 和证据；同一 worktree 不由多个写入者操作。
- 审查者单独阅读 diff、边界、负例、复杂度和证据，记录发现及处置，不能仅转述作者总结。高风险需独立审查轮次或人工复核，保留既有门禁要求。
- 集成者只串行合入已满足条件的 PR，保存合并前 main、head、最终 merge SHA 和集成报告；上一项集成未验证不得继续下一项。

一个人可以承担多个角色，但要分开执行与记录。GitHub 作者不能批准自己的 PR；单人模式采用单独复核记录，不伪造 Approval。需要强制他人批准的高风险任务若无人可审，保持 Draft/阻断，不通过管理员 bypass 消除要求。有第二位合格审查者后，可另行授权启用 required approving review。

## 2. 拆分与共享文件

一个任务应是可独立验收的有限切片，不将整波并行工作塞进一个长寿分支。分支名用 `codex/<task-id>-<slice>`，main 是唯一持续集成主线；不新增长期 develop 分支。

公共类型、API schema、Cargo/依赖锁、catalog migration、harness/CI、组合根及根文档属于共享热点：计划指定单一 owner 与交权顺序，其他任务通过依赖 PR 提需求。两个任务需要改同一热点时拆出前置 PR，或串行交接；文本无冲突不代表合同兼容。纯 PR 流程不能自动分配锁，owner 表须由协调者维护。

默认所有 PR 的 base 为 main。依赖尚未合入时，下游可按冻结合同/fixture 编写模块实现并建 Draft PR，但标明 blocked-by 与 module-only 证据，不声称真实集成通过；上游合入后 merge 最新主线、替换 stub 并重新验收。默认不从别人的未合入实现分支派生，不跨包 cherry-pick 复制实现；确需堆叠 PR 时先记录 base、顺序和重新指向 main 的复核计划。

| 任务 | owner / 文件域 | 基点/合同 | 依赖 | PR / 复核 / 集成证据 |
| --- | --- | --- | --- | --- |
| 示例：catalog资源 | 指定负责人；catalog资源子模块 | 填实际SHA/版本 | 公共合同PR | 填链接与状态，不预填通过 |
| 示例：对象读取 | 指定负责人；storage读取子模块 | 同一冻结合同 | 公共合同PR | 可与catalog并行；共享锁文件另交owner |

## 3. 创建隔离任务

先核对原目录 Git 状态、task-status 和现有 worktree，保留 dirty 文件。以下占位符必须换成任务实际值；命令在指定目录执行，不能照抄同一个目录名启动多个任务。

```sh
git status --short --branch
git worktree list
git fetch origin
git worktree add -b codex/<task> <absolute-new-worktree> origin/main
cd <absolute-new-worktree>
# 按 harness/README.md 建立 .venv 并安装本版本的锁定依赖
.venv/bin/python scripts/harness.py install-git-hooks
.venv/bin/python scripts/harness.py task-start --label <task> --objective '<验收目标>'
.venv/bin/python scripts/harness.py plan
```

每个 worktree 的 task 状态独立，Git 对象、refs、仓库级配置和 checkpoint/evidence 存储共享。worktree 隔离源码，不隔离 Docker、端口、PG、对象前缀或 CPU/内存：任务给外部资源唯一名称并记录清理责任；测量性能时串行独占固定环境，不能把相互干扰的数据当 baseline。不提交 artifacts、凭据或真实用户数据。

已有 main 上的 dirty 任务迁移：保留原目录和 active receipt；新 worktree 从其原始基点创建任务分支，将经确认属于该任务的 diff/新文件复制到新目录，复核路径、内容和遗漏后重新 plan/check。不得自动 stage/stash/清理原目录；旧任务在新任务可接续后由其负责人 task-abandon，注明承接位置。迁移前不让两个目录同时继续该任务。旧提交保留历史，不重写已推送记录。

## 4. 分支验证、推送与 PR

按[开发流程](development-workflow.md)先写用户合同、实现正负例并运行适用 check；只 stage 任务文件，复核 staged diff 后提交。pre-commit 必须启用，禁止 `--no-verify`。提交后重验原始 task base，task-finish 绑定当前分支 commit、报告和 checkpoint；分支结项不等于主线交付完成。

```sh
.venv/bin/python scripts/harness.py check
# 审查通过后，显式 git add <本任务文件>、git diff --cached --check、git commit
.venv/bin/python scripts/harness.py check --base <task-original-base-sha>
.venv/bin/python scripts/harness.py task-finish --report <report.json> --review '<发现与处置>'
git fetch origin
git push -u origin codex/<task>
```

推送前核对远端分支：若已被他人推进，先保留现场、正常 merge 并重验；禁止强推。推送授权包含创建 PR，使用 GitHub 连接器或网页 New pull request：base=main，compare=任务分支；未完成使用 Draft。可用 GitHub CLI 时等价为 `gh pr create --base main --head codex/<task> --draft --title '<标题>' --body-file <实际正文文件>`，CLI 不是 harness 的必需依赖。

使用[PR模板](../.github/pull_request_template.md)填写原始 base、owner/范围、依赖、验收/拒绝、证据、恢复和独立复核。每次追加提交、冲突处理或同步主线均重新对原始 base 按实际影响层级检查并更新 PR；旧 head 报告仍保留原义，未经明确完整输入闭包复用协议不能伪装成本次执行；若已 task-finish，同一分支以新的 label 启动 follow-up task，最终用显式原始 base 的 check/checkpoint 覆盖完整 PR 范围，不把 follow-up receipt 当作旧任务全部证据。

## 5. 合入条件与串行集成

合入前逐项核对：

1. PR 为 Ready、目标 main、依赖已合入、文件范围与合同一致、对应 module/pair 或更高层证据成立，审查发现均处置；高风险独立复核已完成，兼容/迁移/补偿明确。
2. fetch 最新 main 并核对其 SHA 是任务分支的祖先。若落后，在干净分支执行 `git merge origin/main`，解决冲突后重新复核和执行完整 PR 原始 base 的 check，再正常 push；不 rebase 已共享分支，不 force-push。原始 task base 保留，禁止缩小验证范围。
3. GitHub 当前 PR 测试合并树的 `quality (Python 3.11)` 和 `quality (Python 3.14)` 均 success。不能用分支 push CI、旧 head 的绿灯、仅 workflow_dispatch、skipped/cancelled/missing 代替。记录 PR head/base SHA、run URL 与 job 结论；证据与当前候选不一致则等待重验。
4. 集成者保存合并前 main SHA 与已审查 head SHA，临合并再次核对主线未推进；如变化，停止并回到同步/验证。通过 GitHub **Create a merge commit** 合入，保留任务历史/receipt 可追溯性；不 squash/rebase merge，不使用管理员绕过。API/CLI 合入须提供 expected head SHA，防止 head 在审查后被替换。

有远端 strict required checks 时由平台同时约束最新主线；没有保护时上述串行核对是协作约束，无法消除外部写入者在检查后推进 main 的竞争，不能宣称技术强制。不得因此自动降级门禁或补推 main。

合并后在新建的 detached worktree 检出精确 merge SHA（不移动已有 dirty main）：

```sh
git fetch origin
git worktree add --detach <absolute-new-integration-worktree> <merge-sha>
cd <absolute-new-integration-worktree>
# 按当前锁定依赖准备 .venv
.venv/bin/python scripts/harness.py check --level system --base <main-before-merge-sha>
.venv/bin/python scripts/harness.py checkpoint --label <task>-main-verified --report <report.json>
```

模块选择器代码合入后，精确主线候选必须显式选择 `--level system`；尚未合入选择器的旧 CLI 使用原完整 change 检查。模块或配对报告不能建立 `main-verified` 系统验收记录。

核对该 merge commit 的主线 push Actions 两个 job 也通过，将 PR URL、原始任务 base、head、合并前 main、merge SHA、分支 receipt/checkpoint、主线报告/checkpoint 与远端 run 组成交付记录。若主线已被外部推进，先验证该精确 merge，再验证推进后的实际候选；停止下一次集成直到范围与证据明确。原 main 工作区若 dirty，不执行 pull/reset，保留并报告待同步状态。

合并后失败：停止后续合入，保存日志/diff/基点，修复或撤销均走新分支与 PR。撤销 merge commit 需先复核父提交和依赖，再在干净任务分支执行 `git revert -m 1 <merge-sha>`，验证后创建 revert PR；不重写 main。代码撤销不恢复数据/外部副作用，按迁移/对账合同补偿。恢复遵循[安全恢复](version-control.md)。

## 6. GitHub 保护设置与实际状态

以下是管理员后续实施的目标配置；远端设置仍需用户另行授权。本轮不调用权限/保护设置 API，不因仓库内有模板就声称保护已启用。

| 目标配置 | 要求与核验 |
| --- | --- |
| main 必须走 PR | 要求 PR、解决对话；限制 bypass，禁止强推和删除；不要求 linear history，因为采用 merge commit |
| 两个必需检查 | 精确选择上述两个 quality job，来源 GitHub Actions，strict/up-to-date；先确认真实 PR 运行已产生这两个 context |
| 审批 | 单人保留 PR+复核记录；有第二位合格审查者后启用至少1人批准、提交更新撤销旧批准；不能要求作者自批 |
| 合并方式 | 约定仅 merge commit；远端实际设置尚允许其他方式时，不称已禁用。auto-merge/merge queue 暂不使用 |
| 平台限制 | 私有仓库保护取决于 GitHub 方案；不支持时明确缺口，不用本地 hook 冒充服务器强制 |
| 落地验证 | 管理员读取有效规则/绕过范围，受控测试直接push被拒绝、缺检查不可合并、新提交使旧批准失效；记录实际结果，不制造破坏性试验 |

2026-10-20通过仓库元数据确认：私有仓库 `yizhouxw/guradb`，默认 main，允许 merge/squash/rebase，auto-merge=false。未读取/修改有效保护规则，保护和审批强制状态保持未验证；本轮 PR/CI 实测在交付报告中另列。

官方依据（2026-10-20核对）：[受保护分支与严格检查](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)、[必需检查与merge queue事件](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)、[作者不能自批及旧批准失效](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/approving-a-pull-request-with-required-reviews)。

## 7. 清理与交接

PR合入且主线验证通过后才可提议清理。先确认工作区干净、无active task、分支/检查点/证据可取；worktree/分支不自动删除，不批量推送 checkpoint。receipt 和 Git 目录归档不是异地备份；Actions artifacts 14天到期前把需长期保存的报告/trace转存授权位置。关闭未合并PR不算完成，task-abandon 留下原因、失败、依赖、现场与接续位置。

## 8. 策略 v2 的连续配对与集成窗口

[策略 v2](../docs/plans/2026-10-21-modular-delivery-v2.md)把需求小片作为任务单位。ROOT 是 PM/串行集成者，按实际四槽控制在制、写权与审查分工；模块稳定后指定真实消费者与最早配对窗，迟于目标窗口须记录阻塞 owner/解除动作。普通隔离单元/功能可并行，性能与共享迁移只独占受控资源。

分支/PR 验证按 module/pair/system 层级选择；当前两 Python quality job 名称与真实候选检查保持。模块通过不要求每次编辑重跑所有数据库套件；公共影响/未知范围扩大检查。ROOT 把稳定小片聚成系统批次，精确 main 候选完成 system 与 main CI 前不推进下一批，I1/I2/I3 教程只能由系统实物提升。全程保留原 base、独立审查、merge commit 与正常推送；不将频率调整变为跳过恢复或发布义务。
