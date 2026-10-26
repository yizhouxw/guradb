# 团队协作：本地任务、稳定成员与有界委派

状态：2026-10-26 用户已批准立即采用，见 [ADR0025](../docs/decisions/0025-local-member-memory-and-task-delegation.md)。本文件是团队职责、技术升级与派发的唯一规范；定向替代 ADR0023 的强制独立 Issue 和固定成员会话规则，保留质量、预算与 CI 暂停。组织登记不代表成员已唤醒或数据库能力通过。

## 角色、知识与代码责任

| 稳定 member_id / 角色 | 责任与交付 |
| --- | --- |
| `pm` / PM | 仅维护全项目交付图、跨角色优先级、唯一DRI、总预算、实际槽/共享窗、用户交付承诺/风险与最终收口；全项目唯一执行会话 |
| `product` / P | 用户场景、支持/拒绝白名单、优先级与可执行用户验收 |
| `architecture` / A | 公共合同/common、模块边界、依赖 DAG、持久化/恢复不变量、版本来源、ADR与技术争议 |
| `development` / 统一开发负责人 | 仅维护已批准交付包内部任务图与subagent实例，负责包内技术拆解→作者自测/修复→预定独审交接→唯一串行集成链；不包揽模块自测，不代T验收 |
| `system-test` / T | 独立真值、具名非作者审查、真实配对、系统功能/性能/故障/恢复、release结论及限制 |
| `integration` / E | 共享依赖与构建入口、热点写权、冲突合成、唯一串行集成与精确main核验 |

| 模块知识/代码责任 member_id | 责任域（实际源码归属仍由 architecture.toml 唯一定义） |
| --- | --- |
| `catalog` | 身份/授权、revision/view、发布、pin、状态与 unknown 对账 |
| `storage` | 对象版本、传输/完整性、缓存、请求/字节预算 |
| `connectors` | 源版本、格式/删除/schema/快照兼容、Parquet/Iceberg和接入 |
| `query` | 唯一 SQL/类型/参数语义、Arrow/DataFusion、执行、融合、回表 |
| `index` | BM25/ANN/图、构建、覆盖证明、候选/定位与质量 |
| `cluster` | 任务/worker生命周期、取消、背压、进程和资源控制 |
| `gateway` | HTTP/PG会话协议、统一客户端、CLI/MCP |

13个责任位均有[项目成员记忆入口](members/README.md)。七模块保留稳定知识和代码责任，具体任务作者由统一开发负责人明确委派；知识责任不自动授予长期文件写权。common由A维护并逐任务指定作者。模块/角色标签沿用[标签清单](module-labels.json)，不等于派发或权限。

PM与development不维护两套调度图：PM决定全项目交付图及跨角色/共享资源安排，development只管理已批准包的内部任务图和执行实例，不另设全项目目标、优先级、用户承诺或全局schedule。PM预先确定A/T接链与资源后，development可直接触发已授权独审和交接，不需PM转发技术细节；没有授权的审查人/资源仍须补齐，不代T验收。所有协作状态只写同一活跃TASK，development向PM提交短结论、限制与下一动作；PM据此协调全局，不复制包内逐命令进度。旧会话长goal/恢复指令只作历史，不能据此扩域。

PM不实现代码、写runner、执行测试/probe、重算hash或逐行技术审查。技术疑义直接交模块作者、A、T或E；PM接收具名结论、范围、缺口和下一动作，不替技术负责人复验。模块作者完成完整owner源码和真实依赖自测并修复；E供应工程环境不接管模块自测，T独立验收不代作者修复。职责可兼任，贡献身份不能通过换角色/会话洗掉。

## 本地权威与预授权包

[任务入口](tasks/README.md)指定的唯一共享活跃根（`/Users/chad/dev/guradb/artifacts/team-state`，host=`local/xiaoweideMac-Studio.local`）中每任务独立 `tasks/<id>/TASK.md` 是派发、范围、状态与交接权威，PM [START](pm/START.md)指向共享根唯一 `pm/CURRENT.md`，它只作当前任务索引及唯一PM/调度状态，不复制任务完整状态。Git管理目录中的 receipt 是 harness 原始基点和生命周期证据；本地TASK引用它，不能手改或用TASK取代 `task-status/finish/abandon`。成员记忆是知识索引，不另建任务状态真值。日常状态/交接/发现以显式单写者轻量保存和人工版本核对，不逐条PM源码任务/全仓门禁/提交；长期规范/知识与任务稳定点受审归档到harness。所有worktree指同一共享根，跨机未同步为unavailable/HOLD，忽略的操作记录不等于备份；普通源码/规范仍保持原门禁。

先查本地任务查重，再按[任务预授权模板](templates/local-task.md)登记：唯一task ID、稳定DRI/贡献成员、执行实例、独立reviewer/消费者、用户可观察验收和拒绝白名单、层级、B/H、分支/worktree/receipt、唯一写域/热点、依赖、资源预算/次数/停止条件/越界升级、证据可取性和下一检查时间。未具名DRI、未定范围/验收/预算不得开工。普通设计→实现→自测→修复→独审→集成作为一个预授权包；同scope内由责任人持续推进，不逐动作请示PM。授权固定单轮与整任务累计资源上限、最多次数及已用额度，修复不重置预算；未提交H=NOT_CREATED，可按当前开发快照/写域设计、编辑、自测，不要求编辑前已有H，冻结审查和提交后报告必须绑定真实版本。扩大合同/文件域/预算、引入新副作用或碰到停止条件先停相关写入并交对应责任人/PM重排，不能自行扩大授权。

统一开发负责人按目标派具体有界任务subagent，不以“帮忙看看”转交无限范围；登记父任务、作者member_id、实际实例和消费者。非PM成员可多session或subagent，每个实例有自己的任务/写域；四个实际槽同时至多两项行为开发，保留独审和系统测试能力，不为均摊创造任务。PM全项目只能一个执行会话，不能再开第二PM。当前授权本次直接main例外由E串行管理，不复制到普通任务。

GitHub Issue可选作外部协作/历史ref；本地task ID是主键，无网络仍可派发、恢复、设计、实现、本机自测和独审。PR、推送、远端head/main未知时记录 `NETWORK_BLOCKED/NOT_CREATED/UNKNOWN`，普通任务停在允许的本地阶段；不得伪造PR或改用直接push main。已发生的远端动作结果未知先对账，保留正常branch/worktree/receipt/hook和[PR流程](parallel-development.md)。旧Issue表单仅是可选外部表单，其中历史必填标签/assignee/session字段不再构成本地开工前置。

## 稳定身份、多实例与独审

member_id为项目内持久身份，不取会话/任务UUID；角色变更不改身份。当前父E的member_id=development，兼任integration角色不成为integration第二成员；未派责任记忆入口不生成新身份或独审权。会话只是执行实例，旧会话结束不使该成员成为新作者。贡献成员集合必须随任务/后继修复保留；reviewer必须是集合以外的不同stable member_id，独立阅读实际diff/必要合同/证据并写发现→处置→确认、PASS/HOLD/FAIL与未覆盖。只换会话、subagent名、GitHub账号或角色不构成独立性；同一账号COMMENT不冒充平台Approval。无人可独审保持HOLD。

每个任务文件域一个当前写实例；共享热点由E串行交权，性能/coverage/迁移重资源独占。每成员记忆profile/knowledge/decisions/tasks指定一个当前记忆写者；其它实例只写自己的 唯一共享活跃根 `members/<member_id>/discoveries/<task-id>/<instance-id>/NOTES.md` 独占发现域，提交带来源/版本/观察时刻的提案，由具名单写者合并并记接纳/拒绝，不并发覆盖记忆。记忆写权不授予产品源码写权。接管前核旧写者已停及证据可取性；未知先只读HOLD。此为人工协作约束，无自动CAS、身份认证或机器全局锁。

## 验证、交接与集成

P给用户旅程→A冻结必要合同→统一开发负责人委派模块作者设计/实现/自测/修复→不同成员独审/T真实配对系统验收→E依赖顺序串行集成→精确main核验。module/pair/system/release分别记账，module不推导system，50–100GB真实三模态/九场景及完整发布目标保留。CI继续 `PAUSED_BY_USER/NOT_RUN`，不删除负例、缩负载、抬预算、弱化覆盖或跳missing。

B=receipt原始基点，H=当前候选，M=临合入main，G=实际merge；都记录完整SHA，当前未产生则写NOT_CREATED/UNKNOWN，不填虚值。作者报告/独审绑定同H；修复、同步main或冲突处理得到新H则旧证据不自动复用。集成遵守[PR流程](parallel-development.md)与[开发流程](development-workflow.md)，提交后原范围check、task-finish/checkpoint和精确M→G独立干净树验证不可缺。用户授权直接main例外记录真实起点和提交结果，不虚构merge事件。

稳定点目标30分钟内指定reviewer/消费者，真实配对目标下一可用窗口、两小时内启动；超过承诺更新事实与排程。同条件两次无新证据失败停止盲试、保留现场并定位根因。超过一工作日阻塞明确重排/升级。PM按[协调规则](pm-coordination.md)连续推进有行动项，仅维护一个有效下一检查点和既有唯一schedule；架构每6h固定锚不因中期review重置。

历史2026-10-24 #34作者→#35独审→#36集成是旧Issue/session合同实例；不作为稳定member独立性已验或当前写权证明。旧报告/失败保留原义，当前身份必须重新按贡献集合核对。交付以main可复现验收出口与缺口衡量，不按credit、活动量或评论数计完成。
