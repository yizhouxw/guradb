# 固定读取组合的测试运行环境（待验证）

此任务只准备验收环境，不改变数据库用户行为、权限、查询结果、支持格式或生产默认值。基点为 C3 `5a208d1`，依赖 Draft PR18；它不是已合入主线的环境。P04 producer 与 Rust 消费者另有独占任务，环境通过不能替代真实 IPC、PG/S3 组合、原始范围门禁或完整发布证明。

## 验收与范围

固定 Python 3.12.12 bookworm 基础镜像 digest，使用现有 requirements-m0.lock 的全部精确依赖与既有 psycopg/psycopg-binary 3.2.10。新 derivative 使用独立任务标签，不覆盖 guradb-rust、guradb-pg-client 或其它已有镜像。记录 Dockerfile、锁、平台、实际镜像 ID、Python 分发版本、pip check 和运行日志；缺包或不兼容保留首次失败，不换浮动版本过关。

第一步只验证环境：实际 import、固定 Rust 工具链编译的小型 ABI/时钟 probe 的动态库、同容器父子进程 Linux boot ID 与 CLOCK_MONOTONIC 区间。probe 不执行查询、不访问用户数据。Rust `Instant.elapsed` 与宿主 macOS 单调时钟不能据此获得兼容声明。

后续单列 namespace 预验：owned PG 为网络 namespace anchor，固定 Seaweed 和 runtime 加入同一 namespace，以既有认证的数值 loopback 访问 PG/S3；不放宽 endpoint 策略。记录版本与服务身份、实际连接/版本对象结果及精确清理。尚未完成该步骤不能称拓扑可用。

预验入口（待实现/验证）：`.venv/bin/python scripts/m0lib/fixed-chain-topology.py --image <精确本地sha256镜像ID> --run-dir <全新artifacts目录>`。该入口只新建唯一命名和nonce标记的本地网络、PG/S3容器与SDK探针；PG只读版本信息，S3只写入本次隔离bucket的两个合成对象版本并核旧版本可读。它不登记、发布或绑定数据库用户查询，不读取现有数据。拒绝非精确镜像、已有运行目录和外部同名/非owner资源；无法确认容器或网络归属时保留现场/HOLD，不清理外部资源。

## 预算、故障与恢复

构建限 900 秒，单个环境 probe 限 30 秒；只在协调后的独占 native/服务窗口执行。所有 probe 有唯一容器名与 owner label，保存 started/argv/PID，超时或 daemon 结局未知必须对账，不能凭一条 absent 推断启动未发生。只清理本任务核验身份的容器；构建产生的独立本地镜像保留以供取证，不触及现有服务或远端设置。

namespace预验总执行预算90秒，独立清理预算60秒；每个Docker客户端最多20秒、最终SDK探针最多30秒，PG服务ready最多15秒，S3服务ready最多30秒（与既有Lab.wait默认一致）。创建/启动结果未知即使后来清理确认也不算通过；保存原始首失败，不自动重试整轮。清理按runtime、S3、PG、网络逆序，在owner nonce和CID一致时移除容器及其匿名卷；网络必须带本次nonce且没有残留endpoint才移除。正常窗口结束逐项保存readback，不能仅汇总“已清理”。

环境安装与进程开销不是数据库性能。未验证真实 Rust 查询二进制兼容性、IPC 数据、取消传播、PG 远端停止、全链 native/RSS 和 full11/130 真值时，逐项保持缺口。最终交付仍需独立复核、正常 hook、原基点 post check、task-finish/checkpoint 与依赖/双版本 CI/main 验证。

首次namespace预验在15秒S3 ready期限失败；实际PG已ready，S3日志停在空leader及内部gRPC拒连，资源均精确回读清理。固定Seaweed 3.97源码在gRPC启动前调用最长20秒的leader backoff；这是源码和日志推断，未采集stack。独立复核后只修正此新环境入口的S3启动期限为既有环境30秒，保留首FAIL，PG15秒/总90秒/清理60秒及全部数据库预算不变；须新实测通过才可称namespace可用。

## 2026-10-23 已实测的有限结果

修正后的独立新namespace运行实际27.336秒、退出0：固定derivative的11分发版本匹配，真实C1受控连接得到PG180006及127.0.0.1，S3同键写入两个不同VersionId并读取旧版本验证内容摘要。3容器/2匿名卷/网络均精确回读不存在，44客户端PID/PGID退出已由作者和独立审查当前核验。首15秒失败保留；实log从空leader到gRPC约16.830秒、到S3 HTTP约22.082秒，与启动等待推断相符，但未采stack。实际报告在`artifacts/fixed-chain-runtime/namespace-startup-corrected/run/report.json`，独立审`b05d1ecb`；这只通过SDK namespace readiness，未执行BIND、P04、Rust查询或IPC。

本轮boot ID与早先foundation不同；今后每次真实组合都必须读取并匹配fresh Linux boot/mono锚点，不能复用任何旧boot观察。完整开发容器另见历史本地开发合同（本次未验收、未合入），其构建/全部锁/import与完整harness入口尚待验证。


## 真实 FD 组合的原请求清理入口（待实现/验证）

本片仅补测试运行时的必要组合接缝，不新增数据库用户可用能力。`scripts/m0lib/fixed-chain-fd-cleanup.py` 将在同一固定 Linux namespace 中，读取 Root 私有目录的原 canonical BindRequest 与 PCF2 配置，复用 P04 的固定配置解码和原 FixedCatalog/ControlledReads 对原请求进行清理；不初始化目录、不重新绑定、不创建第二套 PG 语义。其依赖 P04 启动入口，不能在未整合依赖的旧树宣称可独立运行。

清理必须使用 Rust 原单次清理绝对 monotonic ns 截止，剩余不超过原 5 秒；读文件、C1 事务、独立回读和结束检查均在该截止内，不重新起算。只有原请求指纹、已发布绑定 SHA、released 标志以及原 pin/lease 身份全部对账才能确认。缺失请求、提交结局未知、错绑定、超时或缺少精确回读均失败/HOLD，不把 absence 当未发生。Rust 仍须先精确 wait/reap 原 worker，再依据该结果决定是否确认清理；清理进程本身不证明 worker 退出或释放 W/producer 信用。

输入只允许本轮 `/evidence/private/` 下的固定文件；凭据不进入 argv、日志或结果。stdout 仅有界结构化清理状态和独立 PG 清理账，异常只投影固定错误码/类型。成功/失败、错误 SQL/绑定前失败的 finally、清理子进程退出与剩余预算均须实际验证；目前仅待实现，不把 Source、普通单元或旧组件结果写成真实 PG/FD 链认证。原 Source/首失败、原基点门禁、full11/dual130、W/256、PR/CI/main 义务保持。


## 真实查询链路组合（待实现/验证）

本轮仅在测试运行时接线，不新增用户可调用入口或支持声明。`fixed-chain-fd.py` 复用本页的原 OwnedLab、固定镜像和 PG namespace；`fixed-chain-fd-client.py` 通过真实 SDK 上传、原 P04 fixture 目标登记/发布和 Rust 薄启动器，依次验证 full11 与 dual130。Rust 使用原 QueryOwner、同一固定 binding 和唯一 SQL/DataFusion 路径；Python 仅生成输入、独立真值与核对结果，不执行产品查询。原两句 SQL 不变，dual130 的 LIMIT 只限定输出，必须从实际已校验计数证明全部130输入及64/64/2分页。

输入使用本轮私有0600文件和0700目录；固定二进制/GFSP/P04/runtime只读挂载。调用前后以实际SHA核对源码、二进制和worker profile，运行时 HELLO 必须测量固定分发/锁/平台。输出不能仅凭result文件存在判通过：必须同时核验 launcher 退出0、最终report、精确worker及cleanup回收、原pin释放对账、非空实际声明/分页计数及全值/lineage独立真值。缺少/错误字段、首失败、结果未知、错身份或超时保持HOLD。

沿用原环境 setup/run90秒和独立cleanup60秒，PG ready15秒、S3 ready30秒。每个原请求查询至多10秒，单次清理原绝对截止至多5秒，每case外层观察共15秒而非重置期限；所有停止与收割消耗剩余时间。原始256MiB/32MiB、provider与wire预算、全部故障/门禁保留。候选worker arena和辅助进程逻辑预约未经实测不能标预算或native认证；正常链路成功仍不能代替这些验收。170秒宿主观察上界尚为拟议（90+60+20调度/停止余量），不是已验证watchdog，也不增加内部任何预算。

Rust 必须立即持有两个实际Child，按原清理截止预留TERM/KILL/wait时间。截止耗尽仍未确认reap时保留原失败和exact pending角色/PID/PGID，交给该容器实际PID1的测试client；client只在原15秒剩余内对已收养的本轮子进程waitpid，不能靠PID存在推定归属或刷新截止。无法证明交接/回收则HOLD，由原OwnedLab精确清理整容器并保留失败，不能把容器移除当查询内清理成功。尚未运行真实链路或故障案例；P04/P05各自普通单元通过不作此处认证。


清理辅助报告整数化修正（待验证）：首轮真实full11已经BIND并读取11行，但清理报告确认失败；worker与helper均exit0/reaped，未完成pin确认/dual130。旧stdout未保存，浮点跨语言canonical不稳定为高可信推断，不能写成已复现的具体触发。该未验收私有辅助报告改为 `cleanup_pg` 恰四键：`version=1`、沿原11PG phase顺序的`counts`与`phase_us`整数数组、`native_memory_bytes=null`；真实秒观察向上取整为微秒，所有数值限SAFE，不输出浮点events。完整/partial仍由顶层`cleanup_pg_complete`区分，未观察为null，非法/超界必须非零且保未知；两端仍严格canonical/身份/字段闭集，不去掉校验，不重置原5秒，不伪造native或费用。须增加科学记数/极小时间、partial、非有限/超界/布尔反例及真实新轮证明，旧失败保留。

该微秒上界使用实际float的`as_integer_ratio`再整数向上取整，避免浮点乘法先舍入丢失1微秒；oversize失败仍输出完整七键与unknown PG，不降成残缺成功。


## 正常链路实物与输出预授验证增补（待实现/验证）

整数清理报告修正后，实际正常 PG→P04→FD→P05 合成 fixture 的 full11 与 dual130 已通过独立复核：实际读取11/[11]与130/[64,64,2]，全结果/血缘、worker/helper精确回收及原pin独立对账通过；首失败保留。该有限证据不认证完整产品、原门禁、provider硬预授、W/native或故障恢复。

本增补只调整既有测试client的验收断言，不增加用户能力或新诊断入口。下一轮复用原两case/SQL/输入/镜像/90+60外层/原10+5秒，核验P05新sameOwner固定FD逻辑应用output预授的typed receipt：spawn前B=4MiB+64KiB、A=8MiB+768KiB，原32MiB共享总额；实测object/A转移守恒、无重复收费、最终known close及exact reap/pin以后仅释放未用信用。旧A/PG/结果真值和清理断言保留；缺字段、未知或错误等式失败，不手填期望成观察。这里只覆盖scope.delivered逻辑output，不据此认证内部序列化、辅助Python、W/native或完整门禁；实现及真实复验完成前仍待验。


## READ FINISH_ONLY 本地延续的真实配对（有限实测通过，完整验收待完成）

下述先行合同及接线待验文字保留为历史，最终有限实测与剩余义务见本节末段。

下一有限验证复用本页既有运行环境与client，不增加用户入口或诊断工具。保留原normal full11/dual130，另加同全输入/SQL/参数的full11-finish-only、dual130-finish-only闭形case，显式请求下一eligible READ在完整接收首FINISH后放弃本地尚未接纳的终账，再以同Owner/原op和PG票据/原截止请求worker缓存FINISH。不得称Unix丢包、EOF、部分帧、损坏或超时自动恢复；这些仍终止。

真实证据须核首raw确实弃除、返回FINISH与首digest完全一致、共享单次retry/32messages不重置、无第二DATA/READ/PG执行、只有一次结算/strictdecode/ACK、原费用守恒和exactreap/pin门。恢复失败须留首可信执行/PG费用下界、原主错及unknown，不能借重放退款。原10秒查询/5秒清理与环境90+60/外170上限不变，不缩原11/130或提高预算；新增case若失败保留原件，不能写成预期成功。mode1 DATA replay、其它操作恢复与辅助/W/native/Root256/原full gates继续待验。

宿主最终汇总也仅接受上述四个case按原normal两项、显式FINISH_ONLY两项的固定顺序完整出现；缺项、重复或额外case均拒绝。此接线增补仍待真实运行，不改变各项成功/unknown/预算/清理断言。

2026-10-24有限实测：P05当前行为完整lib198（原187保留加11项负例）、原example10/build通过；真实PG→P04→FD→Rust一次执行normal full11/dual130及两对应finish-only，原11/[11]与130/[64,64,2]及全结果/血缘通过，host31.210秒，原预算未调。恢复均原op2/PG9/ordinal0、首raw弃除/相同cached digest/一次结算/零DATA重放，PG总票据15/25及11counts与normal相同；扣除startup身份长度差后操作wire/extra增加496B。已核B/A守恒、exactreap/pin及全部环境清理，实测原件见`artifacts/fixed-chain-runtime/fd-assembly-finish-only-v1/terminal-review.json`，独审SHA `9d51990ffe5d1e9451ad2e63290dc82d2e9fe98240239909906b7d355057f4bb`。首静态/编译失败保留。此仅固定合成fixture的显式本地READ FINISH_ONLY；mode1 DATA replay、其它恢复、辅助/序列化/W/native/Root256、原完整fault/workload/gates、双CI/精确main均未验收，未新增主线产品支持。
