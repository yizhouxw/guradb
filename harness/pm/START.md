# PM离线恢复入口

唯一活跃根为 `local/xiaoweideMac-Studio.local:/Users/chad/dev/guradb/artifacts/team-state`，所有worktree显式读同一根，不能各自创建CURRENT。先读该根的 `pm/CURRENT.md` 和 `tasks/<task-id>/TASK.md`，再读[团队规范](../team-collaboration.md)、[PM协调规则](../pm-coordination.md)，最后按责任读取[成员记忆](../members/README.md)。离线不必先访问GitHub。[归档CURRENT](MIGRATION-20261026.md)只作最后归档快照。共享活跃根已被现有artifacts忽略规则排除提交，不是异地备份；缺失或跨机未同步时标unavailable/HOLD，由具名owner核已停写及可取副本后恢复，不能从旧快照直接接管。CURRENT仅索引与PM/调度状态，任务进度以各TASK为准；receipt须在正确worktree运行 `task-status` 核对，不能从文档推造。

日常任务/状态/交接/实例发现由显式单写者在活跃根本地保存并人工核版本/结构，不逐条发源码任务、不逐条跑整仓门禁或提交main。长期知识/角色/决定批量审查后归档到harness/members；完成/交接稳定点按任务复制必要小摘要和证据索引至harness/tasks，归档副本标时间与活跃来源。规范与源码变更仍走原门禁/PR，禁止把产品代码放artifacts规避验证。

1. 核自己的稳定member_id/执行实例、PM唯一owner与代际；非当前PM不得冒充PM进行项目级排程或修改schedule；开发负责人按TASK预授权委派仍可继续，接管不明只读HOLD。
2. 读取当前任务原始B/H、写域/贡献集合/预算/停止条件，查看Git状态和现有receipt；旧PASS/旧grant不续用。
3. PM维护全项目交付图、跨角色优先级、总预算/槽/共享窗、用户承诺/风险和最终收口；development仅维护已批准包内任务图与实例。PM预定A/T接链和资源后，development直接触发已授权独审并按原链交接，不经PM逐条转发技术细节、不代T验收；只在同一活跃TASK更新并向PM报短结论/限制/下一动作。旧会话长goal/恢复指令仅历史，不据此扩域。能执行的责任链在同scope继续，交技术角色执行技术工作。无新进展保持安静；未知/过期证据如实记录并给下一责任人。
4. 只维护既有唯一schedule，先核实际平台回读；schedule引用不证明精确one-shot或机器全局锁。架构下一固定锚22:00 Asia/Shanghai，之后每6h，不因中期review重置。

建议schedule短prompt（仅建议，不执行平台更新）：

> 在 /Users/chad/dev/guradb 先读 harness/pm/START.md 指定共享根的 pm/CURRENT.md 和当前本地TASK，核唯一PM会话、代际、成员身份与写权后连续协调；技术工作交责任人按预授权包推进，未知证据和过期授权保持HOLD。只维护既有唯一调度，架构按22:00固定锚每六小时复查；仅实质进展、失败或需用户决策时通知，其余安静。
