# 概要设计与并行实施计划复审

日期：2026-10-20。任务：`outline-design-parallel-plan`；原始 base `fe0a70c8a6d8451acaa21e160a5adde0c0c8e2f2`，`main`干净起点；范围见[变更记录](../design/outline-design-change-plan.md)。本轮不改运行时、API schema、持久布局、依赖或门禁。

## 交付与验收映射

| 用户要求 | 对应交付 | 本轮能证明的边界 |
| --- | --- | --- |
| 整体业务场景分析 | [总纲](../design/outline-design.md)§2–3，B1图文知识库/B2同语料训练/B3后续音视频与S1–S5 | 场景假设、用户结果和负例完整；没有客户调研或业务样本实测 |
| 技术/功能架构与关键技术 | 总纲§4–8，[技术参考](../architecture.md)、[功能架构](../product/functional-architecture.md) | 共同对象/目录/查询、权威边界和替代条件；不证明新增算子或兼容 |
| 模块边界与松耦合 | [模块合同](../design/outline-module-contracts.md)，[ADR0018](../decisions/0018-outline-design-and-module-contracts.md) | 既有机器DAG不变，唯一owner/端口/状态/预算/错误/版本与真实集成门槛；schema实现仍待P00 |
| 部署、性能、观测、云、安全合规 | [运行治理专题](../design/outline-runtime-and-operations.md) | 场景/竞品→目标/方案/验证；五云认证矩阵和候选测量目标不等于云支持/SLO/认证 |
| 每部分有竞品依据 | [官方证据R01–R09](../research/2026-10-20-outline-design-evidence.md)及各专题就近来源 | 七产品、云API和工程规范的文档研究，区分版别/日期与设计推论；无竞品部署对跑 |
| 可并行任务与实施计划 | [P00–P20和W0–W8](../plans/2026-10-20-parallel-delivery.md) | 四槽位、模块文件域、合同/真实依赖、交付物、验收、估算与旧D/A映射；未启动这些实现包 |

## 独立内容审查与处置

研究子任务在完成其证据文件后只读审查总纲、ADR、模块和计划；运行治理子任务只读交叉审查研究、总纲、模块与计划。主任务另行核对研究关键官方事实、机器DAG、现有预算文件和全部差异。作者自己的摘要不作为独立通过依据。

| 发现 | 处置与复核重点 |
| --- | --- |
| 各稿S↔J映射、源提交阶段名不一致 | 固定S1=J1、S2=J2+J3、S3=J4、S4=J5、S5=J6；统一prepared/committing/committed及未知对账/aborted语义，稳定枚举P00冻结 |
| catalog状态权威与调用执行port的文字有歧义 | query应用编排调用源/构建/调度port；catalog只持久状态、授权、pin和发布/回收决定，不反向依赖执行模块 |
| GC必须确认源引用，却不能catalog反向调用connectors | 补源保留/格式维护port与回执，由query编排、catalog登记、storage受限删除；格式仍引用的对象不直接删除 |
| 部署D编号与产品域D编号冲突；Milvus旧2.x链接被当3.0证据 | 部署改E0–E3；架构引用改当前入口并区分职责借鉴与3.0.x能力，不外推历史版本 |
| P15安全传输与P17选型后实现存在循环等待风险，多云包范围过宽 | 拆最小安全前置、首云完整治理/供应链和额外provider认证，分别估算/排窗；未宣称的云不阻断单云发布 |
| 关键路径尚无人员/资源计算；P12与P08并行时合同依赖含糊 | 改列关键汇合路径候选；配置/metric合同在CF1冻结，P12不等待P08实现；实际排期在P00/P01后重估 |
| HA/PITR可能只交边界说明、默认媒体代理缺具体工作包 | P18补实际主备/WAL/旧主fencing/时点恢复；P08/P10负责媒体入口/固定版本取字节，P17负例、P13真实消费，不能只交URI |

最终段落和门禁结果由本任务完成证据绑定；仍未验证的技术选择、真实业务价值、多机/真云成本、数值SLO和合规效果保留待验证，不标“已实现”。

## 验证与证据口径

执行 `git diff --check`、`.venv/bin/python scripts/harness.py plan` 和默认 `check`；按文档变更执行contracts、harness-tests、policy、repository。提交hook检查提交快照，最终提交后再按active task原始base执行check，再task-finish核验范围/日志并建立checkpoint。最终命令结果、commit和报告摘要以该receipt为准。

本轮没有数据库功能/性能变更，不重跑无关运行时负载，也不把文档门禁当数据库质量或发布通过。所有原M2/M3/M4、严格覆盖、质量/性能/故障义务保留；远端CI是否通过需其对应commit的实际记录，不能由push成功推导。
