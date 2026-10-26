# 稳定成员记忆与执行实例

项目member_id是持久身份，不能取任务/session UUID。角色变更不改member；会话/subagent仅执行实例，作者和贡献成员跨实例保留。下表是责任位和已初始化记忆入口，不代表全部成员已派发或13个并发会话。

| member_id | 角色/责任记忆 |
| --- | --- |
| pm | [PM](pm/README.md) |
| product | [P](product/README.md) |
| architecture | [A/common](architecture/README.md) |
| development | [统一开发负责人](development/README.md) |
| system-test | [T](system-test/README.md) |
| integration | [E](integration/README.md) |
| catalog | [catalog](catalog/README.md) |
| storage | [storage](storage/README.md) |
| connectors | [connectors](connectors/README.md) |
| query | [query](query/README.md) |
| index | [index](index/README.md) |
| cluster | [cluster](cluster/README.md) |
| gateway | [gateway](gateway/README.md) |

每成员README分profile/knowledge/decisions/tasks，是受审版本化长期记忆与任务索引，不复制活跃任务状态。活跃写者/实例登记、短记忆和发现放唯一共享根 `/Users/chad/dev/guradb/artifacts/team-state/members/<member_id>/`，host=`local/xiaoweideMac-Studio.local`；所有worktree指同根，不各建一份。记忆单写者在 `CURRENT.md` 登记，其他实例只写 `discoveries/<task-id>/<instance-id>/NOTES.md` 独占追加域，不覆盖他人记录。单写者具名合并并记录接纳/拒绝/来源/版本，长期事实稳定点批量审查归档本目录，日常保存不逐条源码门禁/提交。

每条可复用事实含相对来源、观察版本/时刻、verified/UNKNOWN/expired、原件可取性与有效范围。来源含本地TASK/相对报告，绝对路径另附host，不复制raw/凭据/大历史。本文登记或引用不证明证据可取；取不到保持UNKNOWN/HOLD。旧快照不得覆盖新记录；接管先核旧写者停止、版本和可取副本，再由新写者签收，未知只读。共享根被artifacts忽略，不是异地备份、CAS、认证或机器全局锁。

角色名相似的目录不是自动身份映射：当前父E稳定member_id=development、role=integration，不成为integration第二成员，integration责任入口当前未派发；独审仍须不同member。任务源码唯一写域与记忆单写权分开；有记忆写权不等于源码权。reviewer必须是任务贡献集合以外的不同稳定成员；换session/角色/新subagent不能洗掉作者。PM全项目仅唯一会话和既有schedule，其他成员可多实例但不得共享同一任务写域。规范见[团队协作](../team-collaboration.md)与[PM恢复](../pm/START.md)。
