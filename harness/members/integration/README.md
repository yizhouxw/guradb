# integration 成员记忆

## profile

member_id: `integration`；角色：E。共享工程/热点、串行合入与精确main核验。 稳定身份不随session或role改变；这是责任记忆入口，不自动派发。当前实例、写权、过期/接管登记读唯一共享活跃根 `members/integration/CURRENT.md`，未登记不得写。源码归属以harness/architecture.toml为准。

## knowledge

父E迁移来源：E199全12 Python fake实际有限接受，ref214/6414337328；2026-10-26观察，原件可取性UNKNOWN，本轮未重测，不替storage full10。共享工程通过不替模块/系统验收。 来源：[团队合同](../../team-collaboration.md)、[ADR0025](../../../docs/decisions/0025-local-member-memory-and-task-delegation.md)；版本=2026-10-26本次候选，观察日期2026-10-26，verified=文档已读取，运行/可取性验证=UNKNOWN；新版本或后继证据需重新确认。

## decisions

采用[成员单写/发现/接管规则](../README.md)，决定依据为2026-10-26用户批准的ADR0025。此合同不授超任务scope权限，不证明机器全局锁。过期授权/不匹配head/不可取证据保持UNKNOWN/HOLD。

## tasks

本目录为integration责任知识入口，当前未指派该member的执行实例。当前父E的稳定member_id=development，兼任integration角色，不因此获得第二成员/独审身份；具体授权读活跃TASK。 当前任务状态只读唯一共享根任务记录，不在本页另记第二份。长期归档写者=具名受审任务作者；日常活跃写者/发现归属在共享根登记。最后初始化：2026-10-26，development；独审/正式归档待本治理验收。
