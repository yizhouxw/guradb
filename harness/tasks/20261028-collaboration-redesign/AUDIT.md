# 协作harness完整审查与整改

日期2026-10-28；责任人pm。范围是项目agent协作规范、成员记忆和恢复入口；未审计/修改数据库或harness执行器实现。用户要求PM亲自治理后已撤销开发作者与架构独审，已有草稿/操作痕迹保留；本报告是PM分析与单独自审，不声称团队独立技术审查。

## 根因、改动与验收

| 发现及仓库/历史依据 | 实际整改 | 可观察验收 |
| --- | --- | --- |
| members/README登记13成员，模块README含member_id/写者；integration职责与development重叠 | 活跃成员仅五角色，七模块与工程/集成知识进入domains；原13份记忆归history | 活跃成员目录仅五个；领域页无新成员/写权；历史身份保留 |
| PM规范只禁止技术，却要求预定接链/转发；本轮PM再次错误委派治理 | PM明确亲自设计/维护协作机制；开发自主负责技术包全链；纯治理PM自审 | 组织问题直接PM处理；技术执行/独验无需逐动作PM批准 |
| local-task含大量无差别必填字段，PR/Issue模板仍以固定角色/session驱动 | 一屏目标卡，技术风险按需附加；子任务最小执行包；Issue仅外部引用 | 一个目标一个状态真值；普通子实例不另造全套组织流程 |
| development长期README仍写20261026当前任务；PM CURRENT持续追加历史；engineering CURRENT仍active旧F | profile只保稳定知识/入口；当前索引与历史拆开，退休旧CURRENT移历史并提供映射 | 新会话可用角色摘要+当前TASK+必要领域恢复，旧active不授写 |
| parallel-development写ROOT=PM/集成者、模块负责人；多入口“本次直接main”可被重复沿用 | 明确跨目标PM/包内开发分工，集成为内部职能；direct-main仅20261026历史任务 | 当前治理仍普通分支/PR，技术质量不被组织例外削弱 |
| 10月27日局部181通过后最终源独验HOLD，无主线交付；止损后没有新开发 | 目标验收和实际交付指标、工具前置必要性、停止后的PM重排责任 | 文档验收当前完成；实际效率需后续真实产品目标验证 |

## 审查覆盖

| 入口/文件组 | 处理与理由 |
| --- | --- |
| 根AGENTS、README、CONTRIBUTING、harness/README | 改职责/恢复导航、历史main例外；纠正同页覆盖阈值旧措辞，未改机器阈值 |
| team-collaboration、pm-coordination、pm/START、templates/local-task、pm-handoff-state | 重写为角色职责、目标包、直接交接、事件消息、简短当前索引及暂停规则 |
| members全13份长期profile、索引、实际共享根members CURRENT | 活跃名册五角色；原profile归档；旧模块/integration/engineering活跃记录退出恢复入口，来源保留 |
| domains及templates/execution-brief | 新增按需知识入口和最小子任务输入；不复制代码/大报告，不建长期模块成员 |
| development-workflow、parallel-development、version-control、ci-cd | 修正与新职责冲突的主动条款，原技术门禁/追溯/资源隔离保留 |
| GitHub Issue/PR模板、module-labels描述 | 去强制PM逐任务贴标签、session定义身份/独立Issue前置；标签名称/颜色/结构不变，描述改知识域，integration标历史职能；技术独验和普通PR约束保留 |
| ADR0023/0025、ADR索引、team-change-plan、pm迁移快照 | 标历史替代和修链接，原当时决定/证据保留；新增ADR0026说明用户决定 |
| 七modules及cli/mcp AGENTS | 核均为代码风险/验证/技术边界，不定义常驻成员；无需改代码owner或技术合同 |
| quality-model、evidence、runtime-onboarding、validation-levels、fixed-chain-runtime及技术模板 | 技术质量/证据协议不是人员制度；只在活跃入口加现行协作导航或明确历史CI/阈值优先级，不重写技术事实 |
| policy/architecture/validation/invariants/workloads/faults/coverage-exclusions/ci-state机器配置 | 盘点为质量/代码归属/历史标签配置，不是活跃成员名册；保留字节和执行行为，禁止借组织整改改门禁 |
| 历史任务/计划/报告与raw | 不回填通过或逐件改写；通过现行入口与历史索引区分，不默认加载 |
| 唯一schedule | 原短prompt已满足恢复入口目的，保持PAUSED；本次不重新配置或恢复产品 |

## 用户追加要求与落实

- 明确撤销#19模式：PM START/协调/团队规范及根AGENTS均禁止从Issue恢复职责、状态或执行权；ADR0022的旧组织条款标历史。远端#19原已closed/not_planned，正文及长期约束评论6404986479补齐撤销标记，原内容折叠保留；6384612117已是历史入口，不再写滚动状态。
- 阶段取舍：新增validation-strategy与ADR0027，核心用例先证资源模型/数据流及关键负例，覆盖/全面矩阵/性能长稳移入强化/发布；旧门禁文档顶部明确新策略优先与机器实现未适配。不改policy/runner/workflow，不冒已实施CI或恢复开发。
- 文档策略与机器的差距列为待实施技术项，不由PM接手修执行器，也不再组织治理讨论。

## 单独自审场景

1. 用户要求分析协作低效：PM直接查仓库/历史，维护机制，不唤醒开发/架构讨论组织问题。
2. 普通产品切片已有场景/合同：PM给一次目标边界；开发自行分工、验证、与T直接闭合，P/A不作为强制串行审批。
3. 两项不相交实现：development分文件/独立实例并行，四实际槽与共享资源照守，不新设两个常驻模块负责人。
4. 旧模块会话恢复：名册已退休；读迁移映射及原贡献，不能从旧active/CURRENT自动写入或冒非作者。
5. 新subagent执行：只读执行包、角色摘要和必要领域；缺依据按需查原件，不导入整段PM聊天。
6. 工具前置失败：保失败/质量，不无界修工具；开发给验收阻断与最小替代，PM负责目标重排。
7. 用户暂停但授权治理：只有PM治理范围执行，产品/schedule继续暂停；新增角色规范不恢复旧预算。
8. 文档/工具通过：只声明治理结果，真实产品增量及效率改善仍未验证。
9. 恢复遇到旧#19提示：忽略其派发/权限条款，现行本地根不可用时明确HOLD，不因历史评论存在恢复旧团队。
10. 核心链路阶段：只声称本条真实用户路径及资源/数据边界，通过不升级为全规模或发布；已选关键测试失败仍失败。
11. 纯治理选择器仍扩大system：保留候选和失败，记录机器适配缺口，不跳hook、不改原测试来凑通过。

以上为规范走查，不是自动化调度或产品运行测试。实际命令/结果、commit和主线状态见共享根同task_id的TASK及最终交付记录，缺失不得补PASS。
