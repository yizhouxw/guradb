# 本地任务预授权与交接模板

模板未授权，复制到唯一共享活跃根 `tasks/<task-id>/TASK.md` 后填实际值，不复制为每个worktree的current。稳定点批量归档；日常更新不逐条提交。必填未知即HOLD，零预算明确拒绝新运行，不能用null当无限。Issue可选。

| 字段 | 实际值（待填） |
| --- | --- |
| task_id / parent_task / record_revision / checked_at | 未初始化；使用绝对时间与时区 |
| member_id / role / actual execution_instance | 稳定身份与实例分列，不能用UUID当member_id |
| contributor_members / reviewer_member / consumer | 保留旧作者、修复者和共同贡献，reviewer不得在贡献集合 |
| objective / observable acceptance / support / reject / non-goals | 未填不得开工；用户文档先行或无用户行为依据 |
| project_vs_package | PM维护全项目交付图/跨角色优先级/总预算/槽与共享窗/用户承诺风险；development仅维护本包内部任务图和实例，不另设全局schedule，不代T验收 |
| A_T_handoff_and_resources | PM预定A/T接链、审查成员及资源后，development可直接触发已授权独审，无需PM转发技术细节；不得由同贡献member自审 |
| single_status_and_PM_summary | 同一活跃TASK为唯一任务状态；向PM只报短结论/限制/下一动作，旧会话长goal/恢复指令不能扩域 |
| preauthorized_chain | design→implement→self-test→repair→independent-review→integration；同scope不逐动作问PM |
| B / H / contract_version | receipt原始B与当前候选完整SHA；未提交H=NOT_CREATED，可据当前开发快照和写域开展包内设计、编辑、自测，不要求编辑前已有H；冻结审查及提交后报告必须绑定真实版本 |
| branch / worktree / receipt / checkpoint | 普通任务独占，明确共享Git管理目录证据 |
| allowed_paths / forbidden_paths / hotspot_writer | 唯一任务写实例/共享E交权，不包含未授路径 |
| level / modules / oracle / real dependencies | module/pair/system/release分别验收 |
| resource_budget / timeout / attempts / used_budget / retry_hypothesis | 明确单轮上限、整任务累计上限、最多次数及已用额度；修复/重试不重置已用额度或累计次数；不删负例、缩负载、抬预算 |
| stop_conditions / escalation_owner | 两次同因无新证据、身份/源码漂移、预算耗尽、越界先停保现场 |
| dependency / next_action / commitment_at | 已授权可做项持续推进，截止含时区 |
| source / observed_version / accessibility / freshness | 相对来源+机器/共享根；verified/UNKNOWN/expired，原件不可取HOLD |
| status / blocked_since / current hypothesis | 不用旧PASS覆盖新H；取消用task-abandon非完成 |
| actual_commands / reports / findings→fix→confirmation | 本地实际证据，独审具名绑定同H |
| PR / M / G / exact-main report / remote state | 网络不可用如实NOT_CREATED/UNKNOWN，不伪合入 |
| archive_source / single_writer / handoff_acceptance | 版本与旧写者停止/新写者签收、证据可取性 |

只给有限小摘要和索引，不复制raw/凭据/大hash清单。普通授权保留branch/worktree/PR、hook/check、原始范围及B/H/M/G；用户另授direct-main例外注明范围和真实提交事件，不虚构merge。
