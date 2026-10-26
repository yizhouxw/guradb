# 本地任务：离线成员记忆与任务委派治理

> 版本化变更计划/归档基线。当前协作状态已迁移至同一主checkout的 `artifacts/team-state/tasks/20261026-offline-governance/TASK.md`；本文件不再作为第二份活跃状态。Git-admin receipt仍独立记录本次真实生命周期。此处的状态和ETA是开始时快照，最终结果由活跃任务及实际提交/报告/receipt归档定位。

- task_id: `20261026-offline-governance`
- state: `implementation_in_progress`
- owner_member_id: `development`
- owner_session_id: `01a16109-3476-7532-8d46-7762c1fea2b3`（本次执行实例，非成员身份）
- original_base: `d83d253cd9e19b3bf0976fc11217660d1ee9eede`
- worktree: `/Users/chad/dev/guradb`
- branch: `main`
- receipt_id: `937f3848fca145ce983539bc04a0d3a2`
- checkpoint: `checkpoints/20261026T123329Z-before-offline-member-governance-de6c4269`
- authorization: 用户2026-10-26在唯一PM聊天明确批准中期方案及成员项目内记忆；本次团队/harness治理直接main例外，普通任务PR流程不变。

## 可观察验收与授权范围

仓库规范一致支持统一开发负责人按有界任务委派subagent；稳定member_id及每成员项目内记忆；本地任务、交接与PM恢复入口可离线读取，GitHub Issue可选。PM全局唯一会话，其它成员可多执行实例，保持四槽/至多两行为作者、唯一写域、作者独审分离，不冒机器全局锁。

仅治理文档、模板与最小当前台账，无数据库/用户API行为变化。保留普通分支/PR、正常hook、适用check与精确提交后/main核验；不改覆盖阈值/排除/CI/原产品目标、F/K/S/X现场或失败。

## 实施与文件写权

- 统一负责人E：仅本TASK及后续验证/集成记录；协调检查、独立审查和唯一串行提交/推送。
- 唯一实现subagent：`/root/governance_implementation`，stable member_id=`development`；根AGENTS/README、harness入口/team/PM/开发/PR/版本规范及必要模板、成员记忆/本地记录/PM恢复文档、新ADR及历史ADR定向替代说明；不写本TASK，不写任何产品或harness执行代码/政策/CI。
- 非作者审查：实现subagent交停后，另一个成员/执行实例只读审差异和实际文档证据，不与作者共用角色自批。

## 依赖、预算与停止

一次性迁移来源：旧19/6384612117 rev353及19/6415815272；只取最小当前状态，完整历史/大raw仍在原处。22:00 Asia/Shanghai每6小时架构锚不变，不更新任何schedule配置。

文档适用repository/policy/contracts/harness-tests按实际plan执行；不为本治理运行产品测试、容器、下载或probe。不扩检查预算，不绕hook；新风险/超域先给准确差额。预计21:05可审候选、21:20独审/检查、21:35完成串行集成，均为条件ETA，失败如实更新。

## 下一动作

启动一个最小上下文实现subagent，记录实际ID/文件域与交接；实现冻结后运行适用check、具名非作者审查、正常提交与提交后精确main验证。当前未运行质量门禁、未提交、未推送；本记录不是PASS。
