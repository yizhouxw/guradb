# P08 固定登记与查询入口：最小先行设计

状态：SOURCE-only 三leaf候选，待独立复核；未实现、未运行、未交付新入口。依据[并行实施计划](../plans/2026-10-20-parallel-delivery.md) P08/W1b/I1，以及[ADR0016](../decisions/0016-user-documentation-first.md)、[ADR0018](../decisions/0018-outline-design-and-module-contracts.md)、[ADR0020](../decisions/0020-product-review-and-vertical-delivery.md)。本文不修改工作包最终义务、公共合同或原质量预算。

## Git、owner 与本次范围

worktree `/Users/chad/dev/guradb-p08-fixed-entry-design`；branch `codex/p08-fixed-entry-design`；原始base/HEAD `1e4f6a6c26eb28982f4b61cc75aa05e290211809`。task `d487cc37573b465d87830febdd53af8b`；checkpoint `20261021T102834Z-before-p08-fixed-entry-design-9ca74858`。root已经从clean main建立task，本轮不重建、缩小base或迁移其它dirty候选。

唯一自有文件为 `docs/user/fixed-entry.md`、本计划和 `docs/design/fixed-entry-scenarios.md`；ignored仅保存本树源码机制note、读前后身份、plan和三leaf指纹。root保留用户导航、共享API/schema、ADR/根计划、组合根/main、harness和锁。本轮不编辑gateway/query/catalog/common生产代码、CLI/SDK，也不安装、运行服务、测试或check；一个bootstrap解释器plan只分类文档，不是matchingvenv或运行时证据。

## 实物现状与最小缺口

| 机制 | 已读源码事实 | P08正式入口前仍需交付 |
| --- | --- | --- |
| 旧Rust HTTP/PG | 启动时manifest Catalog和auth_file；HTTP排队句柄/分页、PG准备与portal复用legacy SQL prepare/execute；PG仅loopback | 不能把原 `/v1/queries` 当P02目录入口；显式启用与迁移、共同身份/绑定/错误、PG固定Describe语义 |
| 旧Python HTTP | scan/search/graph/export通过legacy service/control/jobs，不走CF1-A新binding | 原alpha保留回归；正式入口不复制其版本/权限/客户端语义 |
| CF1-A | strict canonical值、固定BindRequest/ReadBinding、独立修改授权/完整target、精确lease释放均有port合同 | port是义务而非真实认证/取消/会计实现；同步Source失败只有error、没有Usage/取消通道 |
| P02当前候选 | trusted host principal、真实PG grant/CAS/receipt/bind与exact release；保护authority首片只认证显式fixture allowlist | 真实认证及源/索引保护authority、正式管理协议、真实授权调用如何受原query取消/剩余期限约束；组件证据不能当公开登记完成 |
| P03/P04 | 同一Python ReadScope/SourceScope计量实际对象attempt与固定批次；authority/cancel callback要求有界无阻塞I/O | PG reauth不能直接替换该callback后沿用其本地时限认证；P04首批完整加载受限源不是大数据按需provider |
| P05 A1a | 共享唯一parser/Compiler和schema adapter；固定scope一次prepare、回调后freshclock、typed参数与原deadline；已有26项库测试记录 | A1b执行器/失败meter/真实Source、PG固定Describe、严格覆盖/完整门禁/PR尚未完成；Prepared不是执行许可 |
| P10/P13 | 负责共同读取、候选回表和跨语言组合根；已有源码级机制分析 | privatebridge的版本/字段/错误/认证、原owner/time anchor、取消/退出证明、失败账本、行血缘与真实PG/Source/Rust实际配对仍未冻结/实现 |

源码机制note仅记录已读固定稿及其SHA，不消费P00未冻结新代码；三leaf不把模块定向通过、历史组件报告或legacy能力当I1通过。根追踪的历史状态由root维护，不在本片跨域修订。

## 不变量与信任边界

1. 一个dataset/已发布view在可信目录原子授权和pin后只绑定一次；全路固定schema/revision/source/artifact/record ID+version，不能“最新”回退、漏read或把物理locator当身份。
2. 认证与wire值分开；外部不能提交可信admin/cleanup角色或自行allow保护目标。当前epoch/到期在status、分页、缓存和最终输出重新检查；pin不授予读权。最后有成本的copy/encode在finalauth之前，回调后重新读取时钟与取消。
3. gateway完整请求指纹、P05绑定后计划指纹、P02持久BindRequest、修改intent指纹分别验证。只恢复原request/query/binding；改参数、预算或主体冲突。跨重启恢复/拒绝与有界账本尚须冻结，不能假称P02请求摘要已覆盖SQL或引入一套P07长期作业。
4. register与publish分离，完整target实体和摘要绑定；源fencing与目录fencing分开。未知修改结果先同intent对账，权限更新不修改原意图；absent reconcile需要目录锁内持久终态，迟到原请求不能再应用。
5. 原父scope贯穿等待、PG、Python、Rust、回表与输出，子预算只缩。失败/重试attempt保留已知费用，unknown不得0填；内存联合活跃与RSS/网络/IPC分域。同步trait、spawn_blocking或丢Future不能证明停止真实I/O。
6. 任何终态均以原精确lease清理，不因撤权跳过、不误释放新lease。清理独立有界且不延长读scope；unknown持久待对账，不宣称完成。部分网络输出不能撤回，半frame失败关闭连接。

关联义务为稳定身份/固定视图、发布与pin、权限、预算取消、格式/完整性及双接口兼容；实际affected_modules/required_suites/invariants以本次plan为准，不手写门禁通过。当前只有文档，生产切片另立原始receipt和文件域，并执行适用完整门禁。

## 切片顺序、接口交接与阻断

| 切片 | 自有完成物/owner | 准入与验收 |
| --- | --- | --- |
| E0 本轮设计 | P08三leaf；root独审并决定导航 | 固定支持/拒绝、场景、owner和pending；只有SOURCE候选，不开放能力 |
| E1 协议与认证冻结 | P08版本化公共请求/响应、能力发现、HTTP/PG错误与请求生命周期；公共A变更仍归P00，root分配共享接线 | 明确endpoint名、closed schema、逐端点尺寸/队列/句柄上限、可信身份来源、请求指纹/账本与重启政策；无此物不可生产实现/自动重试 |
| E2 真实目录适配 | P02拥有PG和migration/权限/CAS；P08只映射协议；真实保护由相应source/index/storage owner提供 | 注册完整target及独立publish/reconcile与认证负例；公开建库/管理接口若不在首片继续明确拒绝，不外露fixture authority |
| E3 query/bridge配对 | P05交付A1b及固定Describe；P10读取、回表与累计费用；P13唯一组合根/私有bridge；P08薄协议适配 | 先冻privatebridge closed wire及可信失败attempt/取消/原owner/期限/身份血缘；可比较受控子进程RPC与nativeport，但本片不选型或冻结生产API，不引入第二SDK/SQLparser |
| E4 I1正式网络验收 | P13集成，P01独立真值，P08 HTTP/PG/薄客户端 | 实际PG+对象+源+索引，经正式HTTP和psql/Psycopg读取同view；全部FE场景/错误/成本/取消/legacy回归，当前源码完整门禁/PR/main证据，不以fake代替 |
| 后续P08范围 | 与CF1-B/P07/P11/P12配对，P13 I2/I3 | 创建/导入、长期作业/句柄、受控媒体代理、CLI/MCP/SDK与完整能力发现、安装迁移诊断仍是整个包/G1义务；媒体SSRF/重定向/私网出口/旧句柄/Range放大须独立验收 |

P13若选受控子进程桥，必须认证精确启动与可信双向协议、stdin/stdout背压/大小、operation identity、取消后socket/进程退出及失败费用完整性；nativeport同样要解决真实阻塞调用的取消/期限，不能凭语言内调用省略。P02当前reauth与mutation自身有界操作不自动服从更短父query期限；如何传递剩余时间和取消是其owner接线前阻断，不能由gateway私自延长或修改A签名。

## 用户文档先行与验证合同

本轮先新增[用户页](../user/fixed-entry.md)和[FE01–FE12场景](fixed-entry-scenarios.md)，均标missing，再由root审查；本轮无行为代码，后续先行diff/提交与task记录必须保存。endpoint/schema/错误冻结后补真实可运行步骤，未启用时不能展示假curl/SQL命令或将纯计划输出称data。

功能比较用P01冻结事实及独立PG18/PyArrow/字面真值，完整int8/NULL/版本、相同投影不同ID、并发publish/撤权/精确lease均覆盖。性能先冻结服务工作集/冷暖/实际费用和所有上限，保留原legacy8192/两文件/5进程cold+warm基线；新入口额外成本单列，不通过缩样本/调质量或产品预算换绿。故障含PG握手/暂停/锁/COMMIT未知、Source半响应、bridge阻塞/断连、输出半frame和cleanup未知；明确触发/返回/最后I/O/实际reap时刻及原子SQL证据。

本次只允许一个bootstrap解释器运行文档plan；没有本树venv/安装、check/test/Cargo/服务或性能数据。后续实际check/正常hook、提交后原base复验、独立复核、task-finish/PR双CI/精确main验证由root排窗；不得用本文SOURCE结论替代。每个真实driver/组合根报告需匹配当前代码与输入，不复用P02/P03/P04/P05局部通过项拼成I1。

## 兼容、恢复与结果

本片只加文档，没有数据迁移、持久表或外部副作用。旧alpha继续显式保留；未来登记迁移保留历史ID、双reader差异与一个发布权威。进程重启、句柄失效、部分输出、未知修改/清理分别处理，不自动重执行、改latest或降级旧入口。回退代码不回退PG或源副作用，持久schema不可盲降级；失败日志/diff和原checkpoint保留，在新目录恢复，原base不缩小。

当前三leaf待root独立SOURCE审查；plan只是分类元数据，结果保存本树ignored，未跑任何质量suite。P08完整包、I1/I2/I3、G1及真实云/HA/生产发布均未完成。遵循用户“本机模拟云环境”：不创建外部资源；共享物理故障域不代替G3/G5、M3/M4真实部署义务。
