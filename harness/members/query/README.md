# query 成员记忆

## profile

member_id: `query`；角色：query知识/代码责任。唯一SQL/类型语义、执行/融合/回表。 稳定身份不随session或role改变；这是责任记忆入口，不自动派发。当前实例、写权、过期/接管登记读唯一共享活跃根 `members/query/CURRENT.md`，未登记不得写。源码归属以harness/architecture.toml为准。

## knowledge

产品执行结果未刷新：UNKNOWN；不得从责任位推定已实现或已派发。 来源：[团队合同](../../team-collaboration.md)、[ADR0025](../../../docs/decisions/0025-local-member-memory-and-task-delegation.md)；版本=2026-10-26本次候选，观察日期2026-10-26，verified=文档已读取，运行/可取性验证=UNKNOWN；新版本或后继证据需重新确认。

## decisions

采用[成员单写/发现/接管规则](../README.md)，决定依据为2026-10-26用户批准的ADR0025。此合同不授超任务scope权限，不证明机器全局锁。过期授权/不匹配head/不可取证据保持UNKNOWN/HOLD。

## tasks

产品后继未派发，见共享活跃根tasks/README.md；无新运行/源码写权。 当前任务状态只读唯一共享根任务记录，不在本页另记第二份。长期归档写者=具名受审任务作者；日常活跃写者/发现归属在共享根登记。最后初始化：2026-10-26，development；独审/正式归档待本治理验收。
