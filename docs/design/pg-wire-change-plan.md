# 变更计划：PostgreSQL SQL 端口与客户端连接

状态：有界本机实现及 PG 功能/组件性能/组件故障子 driver 已本地通过；首轮完整门禁因基点已有的进程组清理竞态失败，必要修复与回归已完成，最终提交的整项门禁与任务归档以 harness/task receipt 为准。范围：M0 Rust gateway/query、PG 协议验收、产品与接口文档，以及阻断门禁的 common/harness 进程组清理修复；不改变 M1/M2 作业执行面。

Git：起始 commit `d95d1ada607fe40a6b1cf8eb19773b3a10f95bae`，分支 `codex/pg-wire`，任务 worktree `/Users/chad/.codex/worktrees/pg-wire/guradb`。用户要求新 worktree；起始工作树干净，无已有用户改动。task label 为 `pg-wire`，恢复点为 `checkpoints/20261018T103351Z-before-pg-wire-0b1be9cf`。最终 commit、精确绑定报告和完成 checkpoint 在最终审查与 task-finish 证据中记录。

## 需求、上下文与非目标

用户要求确认是否能使用 PostgreSQL 客户端和 SDK 直接连接 SQL 端口，并在缺失时补齐产品技术文档与功能。起始版本只有 M0 HTTP SQL；M1/M2 使用的 PostgreSQL 是内部控制面，不能作为 GuraDB 客户端 SQL 端口。沿用仓库名称 GuraDB，用户消息中的 FloraDB 不触发项目重命名。

目标是在同一 Rust gateway 增加可选 `pg_listen`，通过 PostgreSQL v3 协议复用现有身份、SQL 白名单、固定 manifest、执行器和资源上限。[ADR 0014](../decisions/0014-bounded-pg-wire.md) 与[运行说明](pg-wire-running.md)冻结首片范围。

用户可观察验收：

1. 未配置 `pg_listen` 时现有 HTTP 服务保持可用；配置 loopback 地址后，真实 `psql` 和 Psycopg 3 SDK 能使用 `principal_id`、token 密码和 `guradb` 数据库连接。
2. simple query 与 extended query/参数化 prepared statement 对同一固定数据集返回与 HTTP/独立真值一致的 int8/text/bool/NULL；SDK 使用 autocommit。
3. 错误密码、错误用户/数据库、撤权、错误参数、非法 SQL、超限、取消及畸形协议都明确失败；连接出错不使服务崩溃，也不产生无限排队或泄漏活动查询。
4. 原有 HTTP、组件性能及组件故障验收仍通过；文档逐项区分已测客户端与后续目录、事务、扩展兼容面。

支持白名单：本机 loopback、非 TLS、协议 3.0、密码认证、M0 单表只读 SQL、simple/extended query、有限 prepared statements/portals、int8/text/bool/NULL、取消与 SQLSTATE。拒绝白名单：非 loopback 监听、TLS 必需连接、业务事务/DDL/DML/COPY、系统目录与会话设置、ORM/迁移自动探测、PG 扩展 ABI、M1/M2 检索 SQL 化、跨机与生产发布。不能把“所有 PG 客户端和 SDK 都兼容”作为结论。

## 风险与不变量

拟议路径 `plan` 映射到 gateway/query；必需 suites 为 contracts、functional、harness-tests、performance-smoke、policy、repository、rust、stability-component。实际变更集合由整项任务的 plan/check 重新计算。

- INV-001/003：PG 与 HTTP 读同一 M0 固定 manifest；无新发布目录、索引与写入权威，不把内部 PG 控制面暴露给客户端。
- INV-007：启动身份与 token 对应，执行点重读授权，长连接与 prepared statement 不能保留已撤销权限；取消密钥不能代替查询授权。
- INV-008：连接、消息、语句、portal、结果与执行数量有界；PG 复用既有扫描/解码/内存/超时预算，断连及取消释放任务。不得把截断伪装完整成功。
- INV-012：真实客户端验证 simple/extended 的类型与错误；未支持事务、目录、扩展和协议功能明确拒绝。
- plan 还保守列出 INV-009/010/011；本片不修改 ANN、格式读取或训练路径，仍运行原有组件门禁证明未回归，不新增对应支持声明。

## 实现步骤与恢复点

1. 冻结 SQL 端口设计、白名单、配置及客户端矩阵，写入产品、架构、接口、路线图与 ADR。
2. 抽取 HTTP/PG 共用的查询提交、身份重验与只读规划；添加有界 wire 解码、状态机、认证、参数/结果编码及取消。
3. 使用真实 psql/Psycopg 3 与独立数据真值验收；补协议负例、撤权、取消与资源上限断言，纳入 functional 门禁。
4. 运行实际变更要求的 check、独立复核；修复后提交。最终 commit 再 check，task-finish 验证原始 base、归档证据并建立 checkpoint；按仓库约定完成主线集成，不自动推送。

没有新持久数据格式、数据库迁移或业务写入。旧配置省略 `pg_listen` 可继续运行；恢复旧二进制前删除新增字段，旧 reader/writer 与作业/pin 不需迁移。回滚仅关闭新端口，不能追回已向客户端返回的数据。阻断时保留日志/diff，按仓库流程从上述 checkpoint 恢复到新目录；连续两次无新证据失败先定位根因，不能以重复重跑替代分析。

依赖变更限定 pgwire 精确 0.41.1（关闭默认 features，仅消息 codec）及对应 7 个新增锁定包，复用 bytes 1.10.1，不更新 Arrow/DataFusion。registry 包元数据已核实 MIT/Apache-2.0 许可与 MSRV 1.89，满足固定 Rust 1.90；有界 transport 与严格 frame 预检的取舍见 ADR 0014。新增依赖的联编、既有 HTTP 前测/正式组件 smoke 和最终门禁分别存证，不声明新吞吐基线。

### 门禁阻断与恢复诊断

首轮完整 pre-commit 报告 `artifacts/harness/20261018T105618Z-23436bdf/report.json` 为失败，contracts 与 harness-tests 在 macOS 子进程清理出现 `killpg` 的 `EPERM`；其余 functional、performance-smoke、policy、repository、rust、stability-component 通过。不能把局部通过改写为整项通过，也不能关闭 hook。

已保留原工作树与日志，执行 `harness.py recover --checkpoint checkpoints/20261018T103351Z-before-pg-wire-0b1be9cf --destination /Users/chad/dev/guradb-pg-wire-recovery`，在独立恢复目录的原始 commit 重现 contracts 失败。`artifacts/pg-wire-cleanup-diagnosis.log` 记录：macOS zombie-only 且 leader 尚未回收的进程组会返回 EPERM，回收后为 ESRCH；存活的同用户进程组及 leader 已退出但 helper 存活的进程组仍可被正常终止。harness 同名测试在恢复目录此次通过，表明相关时序不是每次稳定触发。

必要范围扩展为 `modules/common/process.py`、`scripts/harnesslib/runner.py` 和各自回归测试。首版在 `PermissionError` 后 poll 确认并回收已退出 leader，再重试组终止；8 项定向回归通过，但第二轮完整报告 `artifacts/harness/20261018T110729Z-565732a0/report.json` 的 harness-tests 再次失败，其余 8 个 suites 均通过。该失败不能忽略，旧修复不足以覆盖退出瞬间的时序窗口。

停止盲目重跑后，独立前序测试实验确认 43 项前序用例没有泄漏 killpg/getpgid/Popen.poll patch；`artifacts/pg-wire-cleanup-exit-window-diagnosis.log` 在真实 owned-process 中测到首次 EPERM 后约 38.5 微秒时 poll 仍为 None，约 1.34 ms 后 wait 可回收，随后 killpg 为 ESRCH。根因是 Darwin 的 PID/组查找失效可早于 waitpid(WNOHANG) 可回收，不能用一次非阻塞 poll 判定仍存活。

第二轮后的清理逻辑只在 EPERM 后允许至多 100 ms 的 cleanup wait，确认进程退出后重试组终止；等待仍超时就重新抛出原 PermissionError，重试仍无权限也继续失败，保留 helper 清理。新增确定性退出窗口回归，独立执行两处清理测试共 10 项通过；原失败/取消/后代清理 14 项针对性检查也通过，见[审查记录](../reviews/2026-10-18-pg-wire.md)。100 ms 仅属于失败后的有界清理等待，不放宽命令运行预算、门禁选择或 SQL 行为；最终完整门禁仍必须重新执行。

随后单独运行完整 contracts 68 项与 harness 67 项，均通过；原始输出在 `artifacts/pg-wire-cleanup-full-suites.log`。这是修复后的两个完整测试套件，不代表第三轮整项 pre-commit 或提交后 check 已经通过。

### A0 合并门禁中断与残余进程组诊断

A0 合并检查 `artifacts/harness/20261018T113925Z-5295b8e4/report.json` 只写入 contracts/functional 通过，随后父 runner 清理进程组返回 EPERM 而中断；其 `harness-tests-0.log` 实际为 82 项/7.727 秒全部 OK，report 尚无最终 `passed` 字段。不能把子进程测试通过视为完整门禁完成。保留合并工作树和日志，从 `checkpoints/20261018T113149Z-pg-wire-branch-verified-ae0d573e` 恢复至 `/Users/chad/dev/guradb-pg-merge-recovery`，恢复目录为干净的 `c48a585e4a79651bcba8178a825037b95a8130e7`。

一次带观测的完整父 runner 和三类共 150 次固定采样没有重现 EPERM；随后受控真实 OS 实验确认：leader 已 wait/reaped，原进程组仍含一个同用户 zombie helper，killpg 连续 EPERM，helper 被其独立父进程回收后约 1.5 ms 转为 ESRCH。该实验定位已回收 leader 后残余进程组的处理缺口，但原 hook 的具体 PID/helper 拓扑没有被记录，仍未知，不能冒称已重现原现场。

修复沿用首次 EPERM 起的同一个 100 ms cleanup deadline，leader wait 使用剩余时间，之后最多每 5 ms 重试 killpg；只有真实发送成功或 ESRCH 可结束，持续拒权到期仍抛原 PermissionError。未增加命令执行预算、总清理期限或门禁容错。独立审查两处补丁和确定性回归，未发现新阻断；父 runner 包装完整 harness 84 项、contracts 109 项均通过，最终 4 项定向回归也通过。报告与原始证据见[复核记录](../reviews/2026-10-18-pg-wire.md)；合并提交的完整 hook/check 仍须完成，不能以这些局部检查替代。

## 验证合同

功能：复用 M0 固定合成 Parquet fixture 和独立 PyArrow/PG18 真值；真实 psql/Psycopg 3 验证连接、simple/extended、命名 prepared、参数类型/NULL、极值整数、结果格式、SQLSTATE、autocommit 及事务拒绝。覆盖错误认证、数据库/协议/消息、权限撤销、连接断开、取消竞争与客户端错误后恢复。

性能：现有 `performance-smoke` 固定数据、容器、冷热与资源预算保持原值；不调整基线以容纳新路径。PG 首片按已有扫描 32 MiB、解码 64 MiB、引擎池 32 MiB、结果 2 MiB/1000 行、并发 2、执行总超时 10 秒约束；协议/连接上限见[接口合同](../interfaces/query-and-clients.md)。未建立 PG 独立吞吐基线，本轮没有提速承诺，不以 HTTP smoke 宣称 wire 吞吐或生产延迟达标。

故障：组件故障 driver 保留 seed/trace；PG 增加畸形消息、取消、撤权与断连资源释放断言。无持久写入/发布变更，不新增未知提交或迁移补偿场景；M1/M2 发布/恢复原有门禁仍需通过。

## 结果与审查

独立源码复核与发现修复见 [PG SQL 端口独立复核](../reviews/2026-10-18-pg-wire.md)；真实回归与整项门禁状态在那里与最终报告分别记录。

### 与主线 A0 的整合

PG 切片提交 `c48a585` 后，主线 A0 已推进到 `23837bf`，两者从本任务原始基点分叉。依仓库流程将 A0 合入本 worktree，再完成合并代码的完整门禁和独立复核，最终回到 main；原始 task base 与恢复 checkpoint 不变。单片的提交后报告不能替代合并结果的代码绑定检查。

接口冲突以 A0 的实际 HTTP/作业、训练、BM25 和本地 worker 合同为主体，加入已经实现的 PG 首片，区分 HTTP JSON/句柄/read_context 与 PG typed rows/会话。README 和文档导航保留两项独立交付；下一阶段计划保留历史排序并注明新增 PG 请求的独立范围，不改写 A0 的历史验收结论。

机器清单 `api/capabilities/v1.json` 新增封闭的 `boundaries.pg_wire`，明确默认关闭、loopback IP、无 TLS、固定 database、token 身份、M0 固定 manifest、只读/autocommit、类型与已测客户端；F05 删除笼统的 PG wire 拒绝，保留 TLS/远程/目录/事务/COPY/ORM/全部 SDK 的拒绝范围。两个 HTTP services、OpenAPI 路由与请求响应字段保持原合同，PG 不伪装为 HTTP operation。相应 schema 与 contracts 负例约束这些声明；离线 source-tree 清单仍不代表部署已启用 PG。

清单/schema 必须从同一 commit 配套读取。新增必填 `pg_wire` 会使旧 v1 清单不能通过新 schema；旧源码快照使用其自身 schema，不宣称跨源码版本无条件向后兼容，也不以此引入运行时能力协商。

整合时 `scripts/m0.py` 同时保留 A0 原始证据/输入摘要和 PG 子 driver 的 trace 绑定，相关合并及回归由主任务另行复核。本文记录整合范围；最终合并提交、完整检查和 main 集成证据仍以本任务 receipt 为准，不提前宣称最终门禁通过。

已执行拟议路径 `plan`，本轮独立 PG 子 driver 的实际报告位于 `artifacts/pgwire-final-target/{functional,stability-component,performance-smoke}/result.json`，三项均通过。功能 72 项断言、故障 19 个 trace 事件、性能 10 个样本；报告 SHA-256、实际运行命令和范围见上述独立复核。子 driver 结果只绑定 trace，不包含 commit/checkout 指纹，不能替代最终提交后 `harness.py check` 与 task-finish receipt 的整项证据。完整 performance/stability/soak 和远端 CI 仍未由本片证明；本地组件通过不等于生产可发布。

PG 新组件 smoke 固定 8192 行/2 文件，SQL 为 `SELECT * FROM documents ORDER BY id LIMIT 1000`，返回 1000 行；SDK 延迟 21.17–58.82 ms，RSS 峰值 53,919,744 字节，满足测试前 10 秒/512 MiB 组件预算。cold-process 仅重启服务，OS/后端缓存未控制；未测 PG 源请求数/字节。其 LIMIT/结果负载与下方 HTTP 前测不同，不能作协议提速对比或产品性能基线。

变更前 HTTP 组件测量在未修改的主线工作树执行：`/Users/chad/dev/guradb/artifacts/pg-wire-before/result.json`，SHA-256 `d6fcb72a2c633cefc070143780906398bf65c590f17337a4250e52fb1e288792`，commit `d95d1ada607fe40a6b1cf8eb19773b3a10f95bae`，checkout digest `c08425e8392badb3341bd005be88d12f1123aaf5f345a19f52afd03d2d5bafb0`。固定 8192 行/2 文件、10 个样本，延迟 94.5–172.51 ms，RSS 峰值 57,892,864 字节。它只是已有 HTTP 组件前测，不是 PG 性能基线；worktree 中曾在源码变化期间运行的同名尝试不作为有效基线。
