# ADR0025：本地成员记忆与有界任务委派

- 状态：2026-10-26接受；角色名册、PM治理职责与协作方式已由[ADR0026](0026-goal-driven-collaboration.md)于2026-10-28定向替代。以下为历史决定；稳定记忆/本地任务/正常质量与PR仍保留。
- 规范：[团队协作](../../harness/team-collaboration.md)、[PM恢复](../../harness/pm/START.md)、[任务](../../harness/tasks/README.md)、[成员](../../harness/members/README.md)

## 决定与替代范围

统一开发负责人按目标交付具体有界任务subagent，模块知识/代码责任仍覆盖七模块，common由A维护。PM仅协调且全项目唯一执行会话；P/A/开发/T/E分责。稳定member_id绑定项目内成员记忆，角色和session是可变属性，非PM成员可多执行实例。作者/贡献集合跨会话保留，不同稳定成员独立读证据才可独审。

共享活跃操作根为主checkout的 `artifacts/team-state/`，所有worktree显式指同根/host，复用现有忽略规则；PM/current、tasks和members发现轻量保存/版本核对，不逐条触发PM源码任务、整仓门禁或提交。版本化规范、长期成员记忆和任务稳定点批量受审归档；跨机未同步或证据不可取只读HOLD，不能当远端备份。普通源码门禁不变。

本地TASK承担派发、范围、状态及交接权威；GitHub Issue可选历史/协作ref，不再每工作强制建Issue。普通设计→实现→自测→修复→独审→集成绑定任务ID/B/H、写域/热点、预算/次数/停止/升级为预授权包，同scope持续推进。离线可本地派发/恢复/开发/验证，远端未知如实阻塞推送/PR/合入。保留普通codex分支、独占worktree、receipt、hook/check/checkpoint、B/H/M/G、真实拒绝与覆盖/预算纪律、CI暂停和精确主线验收。

每成员保留profile/knowledge/decisions/tasks及独占实例发现域；具名记忆单写者合并，任务源码写权独立登记。事实需来源、版本、观察时刻、可取性、verified/UNKNOWN/过期；不复制大raw。PM从仓库稳定START/CURRENT恢复，仅唯一既有schedule；接管核旧停止与证据可取，unknown只读HOLD，代际字段不构成机器全局锁。

定向替代ADR0019/0023中的强制Issue、以固定session定义成员身份及旧禁止任务subagent的组织规则；历史决定和失败保留原义，不回填成功。此次用户授权治理直接main例外仅本任务，由E唯一串行提交/正常hook/推送核验，不扩散普通任务。

## 取舍、验证与恢复

本地记录降低网络和长会话依赖，增加人工版本核对、单写者和证据可取性管理；没有新执行器、锁/调度服务、自动CAS、身份认证或机器身份强制。成员目录是已初始化知识入口，不表示13席都已派发/唤醒。

本次仅治理文档、模板、成员记忆和最小本地台账，不改变harness运行逻辑、数据库接口/权限/预算/格式，无数据迁移或数据库用户行为变化，因此不新增产品场景/性能测试。文档静检、plan、适用check与独立审查证据由本任务和集成记录绑定，不能推导数据库质量/release通过。恢复先读START→CURRENT→TASK→成员→task-status/Git，过期授权/远端未知不续写；保留旧现场与非破坏checkpoint恢复。50–100GB真实三模态/九场景及完整发布仍未验。
