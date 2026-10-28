# 团队与本机质量治理变更计划

历史：2026-10-24合同及当时验证记录；强制Issue和固定会话组织规则已由[ADR0025](../docs/decisions/0025-local-member-memory-and-task-delegation.md)定向替代，不是当前派发前置。当前五角色与PM亲自治理见[ADR0026](../docs/decisions/0026-goal-driven-collaboration.md)。

任务[#20](https://github.com/yizhouxw/guradb/issues/20)，2026-10-24，用户授权本次直接提交main。准备基点8e925532；隔离树用于准备，ROOT唯一串行提交main，不创建额外PR。

验收：固定七模块DRI及产品/架构/专职系统测试/集成/PM分责；每位成员后续任务独立Issue、主模块/角色标签、唯一DRI和验收；现有Actions远端disabled、PR不等CI；本机自测/独审/证据/预算保持。没有数据库用户行为、持久格式或数据迁移变化。

范围：根AGENTS/README、harness协作/Git/CI/开发入口、ADR0023与旧决定后继导航、Issue/PR模板、模块标签及CI阶段JSON、现有CI测试的两项正向托管容量入口。模块标签通过GitHub API创建；workflow通过API停用，配置/历史保留。未修改生产代码、harness选择/执行逻辑、policy命令、数据/预算/strict。

原CI容量测试在暂停模式明确SKIP（不是PASS），覆盖全ready总量及后续profile正向入口；超360分钟和未来planned转ready的负例、runner的missing失败语义继续执行。本机原命令时限/输入与模块/系统/release全部义务不变。CI恢复需显式决定、重新检查容量再启用。

验证：plan选择contracts/harness-tests/policy/repository四套件；新增表单YAML/标签JSON与远端标签/状态核验；独立复核治理边界；最新main应用后正常hook/提交后原范围检查。初次repository门禁发现历史诊断workflow路径在当前树缺失，已修正文档为历史登记，失败报告保留，不调整门禁。

风险与恢复：远端保护规则读取403，不声称已变更或已确认不存在；只取消本轮CI协作准入，其他审批/权限不变。模板不自动贴标签，PM派发前人工核对。旧PR同步不得覆盖最新用户治理决定。回退代码不自动重启远端Actions，恢复须独立对账。当前已发生的workflow停用和label创建保留真实记录。
