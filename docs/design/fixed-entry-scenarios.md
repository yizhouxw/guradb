# 固定入口场景与验收映射

状态：先行设计，全部新场景 `missing`。对应[用户合同](../user/fixed-entry.md)与[变更计划](fixed-entry-change-plan.md)。本文不冻结 endpoint 名、HTTP schema、PG 适配签名或 bridge 协议，也没有运行产物。旧 alpha 的已验收能力保留在[原接口合同](../interfaces/query-and-clients.md)，不借用为下表结果。

## 共用前置与真值

未来用实际部署的版本/能力响应冻结输入白名单、消息大小和错误映射，再绑定同一源码、锁、schema、fixture、配置摘要与独立真值。P01设计样本保持全11条可见事实、完整 int8/NULL/版本及重复投影值，不用生产 Compiler 或排名器生成 expected。关系逐值/选择集合及排序用独立 PG18/PyArrow/字面 oracle，对齐稳定 ID/version 和 schema field ID；无 ORDER BY 不比较未承诺的行序。

HTTP 与 PG 两条真实网络路径须使用同一已登记资源及原始输入；不以两个语言各自单元、fake Source 或直接调用内部方法算端到端通过。执行时另冻结有界工作集、seed、并发、冷暖、每次原 deadline、费用与停止等待。表中的“零读取/零副作用”只适用于明确的准入前拒绝，并须有实际账本/独立 SQL 证明；不能从报错猜测零成本。

| ID / 用户目标 | 成功与独立断言 | 负例、故障及费用/恢复断言 | 前置 owner / 当前证据 |
| --- | --- | --- | --- |
| FE01 发现部署能力 | 取实际版本、启用操作、格式/类型和限额；缺能力明确拒绝 | 未知版本/必需能力、离线清单与部署不同、未启用新入口；不回落 legacy | P00合同、P08协议、P12/P13部署；missing |
| FE02 认证与资源隔离 | HTTP、PG身份映射到同一可信 tenant/subject/delegation，最小 grant 生效 | 伪造请求体身份/admin、跨租户 query/cursor、过期/撤销token、错误消息泄漏、伪委派；脱敏日志不留token/SQL/参数 | P08认证、P02当前grant、P13可信注入；missing |
| FE03 完整登记与独立发布 | 可信操作者预置dataset；同一完整描述符登记一次，独立SQL核revision/target/receipt；独立publish后可绑定 | 摘要/源版本/schema/模型/覆盖不一致、无保护或伪proof、已有operation换目标、旧owner、CAS冲突；register不自动publish；拒绝无部分效应 | P02/P03/P04/P06真实保护与owner，P08协议；fixture authority不足，missing |
| FE04 未知修改结果对账 | 在真实COMMIT/响应边界丢失后，以同operation/fingerprint和当前授权取得同一终态；独立SQL核至多一次 | 迟到原请求与absent reconcile竞争、旧授权到期后重授权、无原action却试图terminalize；不能仅查不到row就判断未应用或创建新ID | P02串行锁/receipt、P08状态映射；missing |
| FE05 固定绑定不漂移 | 查询绑定v1后并发发布v2；HTTP各页、PG portal、检索与回表全属v1；新查询才取v2 | explicit不可用、绑定响应丢失、相同query换完整BindRequest、released/expired身份重放、无索引；不重新follow published/续TTL | P02原子bind/pin、P08请求账本、P10/P13；missing |
| FE06 同请求与同SQL语义 | 精确记录完整外部指纹、P05绑定后指纹和A绑定摘要；相同身份重放只取原状态/结果；HTTP/PG逐值与独立oracle相同 | 换SQL/typed参数/selector/预算/主体复用ID冲突；完整int8两端、规范拒绝、NULL/缺参数、多余参数、4096/4097字符和raw/escaped cap；重启账本缺失拒绝恢复 | P05唯一Compiler、P08协议与恢复合同；A1a有模块记录，服务missing |
| FE07 Prepare/Describe与执行分离 | 同一schema下参数/字段metadata正确，prepare不读源且不伪造执行Usage；首次执行使用已验证原scope | 未授权schema、只读绕过、未知fieldID、SQL失败仍消耗一次性admission、重复准备/执行、伪造Prepared；不能跳过原parse→count→prepare→infer边界 | P05固定Describe接口及A1b未交付；missing |
| FE08 权限覆盖缓存与输出 | 每次status/page/portal继续/缓存命中/最终交付当前重授权；最终回调后freshclock/cancel；精确验证结果与身份血缘 | 各检查点之间撤权、epoch变动、grant/pin/源保护到期、回调迟到或墙钟回拨；最后copy/encode计费且无过期新输出；已交付bytes不声称撤回 | P02/P03/P04/P05、P08/P13桥；missing |
| FE09 取消、期限与后台退出 | 单父scope跨等待/PG/Source/Rust/编码/网络输出；真实CancelRequest/HTTP取消/断连后有确定停止与精确pin清理 | PG握手黑洞/暂停/锁等待、对象卡header/body、native计算、IPC断连；记录触发/返回/最后I/O/close/reap时刻，unknown hold；不能丢Future后声称停止 | P10/P13真实bridge、P08协议；无I/O回调证据不足，missing |
| FE10 成功与失败总账 | 所有attempt有实际计数和同scope累计费用；delta不双计、内存联合活跃与RSS分列；完整结果最后确认 | 失败batch缺Usage、retry多次、ledger owner替换/回退、counter未知、编码/输出/IPC cap、SQL LIMIT后尾批损坏；不0填/不退款/不将部分结果标complete | P03/P04账本，P05 A1b私有meter，P10/P13聚合；missing |
| FE11 精确lease与句柄恢复 | 完成/失败/取消释放原pin+lease，重复幂等，可信cleanup在撤权后仍可清理；状态与结果保留范围明确 | release响应未知、旧lease误释放新lease、句柄伪造/过期/跨租户、网关重启/会计中断；不重建执行/不腾目录身份/不静默续租 | P02、P08恢复账本与P13清理；missing |
| FE12 PG/HTTP兼容和拒绝 | 真实psql/Psycopg autocommit simple/extended与HTTP同数据/参数/错误；新能力显式启用，原alpha回归 | DML/CTE/JOIN/多语句、事务/COPY/SET/目录探测、恶意frame/长度/编码、portal超限和Sync恢复、发送半frame后关闭；不加第二parser/SDK语义 | P05/P08协议冻结、P13真实网络；missing |

## 性能与故障验收纪律

未来有界入口总预算必须在执行前冻结：请求体/响应体、句柄/statement/portal/队列容量、授权和bridge等待、输出保留、父scope及清理预留分别写明。采用最小宿主/请求/CF1-A预算，不能因接线成本调松旧性能、既有工具超时或质量阈值。这里不预设未来selector命令数，也不把本次文档plan当已跑suite。

保留 legacy 原8192行、两文件、5新进程各cold/warm一次等原基线；新入口自己的工作集、warm/cold和并发另冻结，不能以11行功能fixture替代性能负载。额外统计PG授权往返、IPC与真实I/O/请求/字节、总RSS、重试和清理成本；原已验证模块的局部数值不能当新服务时延。

每个成功及失败样本须保留安全请求指纹、原binding/固定版本、输出typed值与身份sidecar、独立真值、实际attempt/费用和退出trace、receipt及独立SQL核对、输入/源码/锁/报告日志SHA。URI/凭据、签名、SQL实参、DSN、私有Lab配置不整包归档；测试只用许可明确的synthetic输入并逐路径选取安全原件。失败也记录明确unknown和部分已知费用，不手填成功或复用错源码数据。

## 本轮状态

只有三份设计leaf及ignored源码机制记录；没有新增HTTP/PG协议、生产代码、运行时、真实取消、数据库认证或对应报告。未来P08协议冻结、P02/P05及P10/P13真实配对后才能逐项更新表格；缺一保持missing。I1共同查询与后续I2/I3、G1完整入口/薄客户端/安装恢复分别验收。
