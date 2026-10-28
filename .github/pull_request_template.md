## 变化与目的

说明用户可观察行为、影响模块及关联 ADR；文档/骨架/真实实现分别说明。纯内部或文字修改说明无用户行为影响。

## 并行任务与合入顺序

- 本地TASK路径 / 稳定member_id与贡献集合 / 执行实例 / 复核方式/技术独立reviewer member_id / 可选Issue ref：
- task ID / 预授权包与预算/停止条件 / owner / 分支 / worktree / receipt：
- PR base（默认 main）/ 原始 task base SHA / 合同版本：
- 允许文件域、共享热点 owner 与交权情况：
- 依赖 PR / blocked-by / 集成顺序（无依赖明确写无）：
- 用户文档先行合同 / 验收案例 / 支持与拒绝白名单：

## 风险与验证

- 变更计划与相关 INV：
- 当前 head SHA、实际命令、完整原始范围报告与分支 checkpoint/receipt：
- 功能正确性/独立真值/差异/负向用例：
- 性能：固定输入、冷热、质量/recall、请求/字节/内存与预算；无关说明原因：
- 稳定性：seed、注入、恢复、发布/GC/取消及 trace；无关说明原因：
- 尚缺证据、兼容/迁移/回滚与外部副作用补偿：
- 证据归档位置/有效期与交接事项：

## 复核与合入条件

- [ ] 文件范围/合同一致，依赖已合入；分支包含最新 main，冲突处理已复核。
- [ ] 当前候选适用本机检查与复核证据完整（技术任务须独验；纯协作治理可由PM单独自审，明确标注）；远端Actions/PR CI当前暂停，记录PAUSED_BY_USER/NOT_RUN，历史失败不写PASS。
- [ ] 单独复核发现与处置已记录；高风险/门禁/持久协议由独立审查轮次或人工复核。单人记录不冒充 GitHub Approval。
- [ ] 由集成者串行使用 merge commit 合入，不 bypass、不直接 push main、不强推。

复核发现、处置与剩余限制：

不要将 bootstrap 通过写成数据库质量通过，不以删用例或放宽预算消除回归。实际操作见 [PR 并行流程](../harness/parallel-development.md)。

## 合并后交付记录（合并后补齐）

合并前 main SHA / 审查 head SHA / merge SHA / 完整合入范围 check 报告与主线 checkpoint / 本机验证及远端CI暂停状态：

失败停止下一 PR，修复或 revert 也走 PR；未填完本节只算分支验收，不算主线交付完成。
