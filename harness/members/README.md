# 五个稳定成员与项目记忆

活跃成员名单只由本表定义。成员身份绑定项目记忆，session/subagent是可替换执行实例；PM全项目唯一会话，其余按任务需要有多个实例。目录存在和旧任务出现某名字都不授予成员资格或写权。

| member_id | 稳定职责与记忆 |
| --- | --- |
| pm | [组织、协作机制、目标与排程](pm/README.md) |
| product | [用户场景与验收标准](product/README.md) |
| architecture | [技术边界与设计裁决](architecture/README.md) |
| development | [统一研发与集成交付](development/README.md) |
| system-test | [独立验证](system-test/README.md) |

七模块与工程/集成知识在[领域目录](../domains/README.md)。它们不是独立成员，不设长期负责人/会话/审批节点。开发subagent通常归属development，在父TASK保留实际作者实例和历史贡献来源；不为每个执行实例增加长期成员目录。历史module/integration/engineering身份已退出活跃名册，但贡献关系永久保留，不能借迁移把作者变成非作者，见[历史映射](history/README.md)。

## 默认只读什么

恢复只需本成员README、当前目标TASK的当前段、任务明确引用的必要领域/ADR。没有本次任务需要就不读其它成员、全量历史、旧CURRENT或大raw。任务派发使用[执行包](../templates/execution-brief.md)，默认不继承全聊天。

成员README保存短profile、稳定决定、知识/历史来源和当前状态入口，不保存滚动任务ID、旧writer或“当前通过”快照。知识分为：职责稳定规则放成员记忆；跨任务技术知识放domains或已有设计文档；进度/失败/候选版本放TASK。可复用事实须有来源、观察日期/版本、适用范围和verified/UNKNOWN/expired；没有新验证不能提升旧事实。

## 写入与恢复

唯一活跃根 `/Users/chad/dev/guradb/artifacts/team-state` 的 `members/<member_id>/CURRENT.md` 只登记该成员的记忆写者、实例与任务链接，任务真值仍是TASK。一个成员一个记忆合并写者；其它实例在各自 `discoveries/<task-id>/<instance-id>/NOTES.md` 写发现，完成后由单写者归纳可复用结论，不搬整段聊天。PM负责组织/记忆结构治理和迁移；成员各自负责职责内知识，不能因此把协作制度交给开发负责。

历史区不自动加载。过期活跃记录移入共享根 `history/members/`，保留旧来源引用索引；旧路径若仍有引用只保留退休跳转，正文不再嵌入旧active段。跨机不可取则记录unavailable，不从历史快照授写。普通产品任务接管先核旧writer停止和Git/receipt；记忆写权不等于代码写权。

技术独验必须来自贡献集合外的稳定成员，development的另一个subagent不是独立system-test。纯协作规则由PM亲自维护并自审，不声称技术独验。当前规则见[团队协作](../team-collaboration.md)，项目暂停/目标授权见[PM START](../pm/START.md)。
