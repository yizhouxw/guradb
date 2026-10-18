# A0 主线集成变更计划

状态：切片实现与独立复核完成；主线最终门禁、commit和checkpoint以任务receipt为准。
任务 `a0-main-integration`，main基点 `d95d1ada607fe40a6b1cf8eb19773b3a10f95bae`，起始干净、没有active主线任务。
恢复点 `checkpoints/20261018T111332Z-before-a0-main-integration-a1210246`。

## 可观察验收与范围

仅实现[计划A0](../plans/2026-10-18-next-stage.md)：实际支持能由源码能力清单与接口/格式文档核对；M0新原始证据完整归档，历史现存字节保持原commit/digest；P0结果可从独立源输入重放，JSON摘要可重算，更新贯穿60秒窗口。
白名单保持M0单表只读SQL、M1/M2有界job与本机三worker、既有湖格式/append语义。
拒绝未支持格式/源删除/schema演进、公开写入、多机writer；不实施A1–A6、不推送。

切片：M0 `f58e690`、能力合同 `cf5b483`、P0 `063ef1e` 及摘要修复 `abc33bc`。
各自干净提交、原始base门禁、独立复核和task-finish已核验。优先快进M0，再正常合并分叉历史；全局文档随最后一次合并提交。保留分支、worktree、旧artifacts及归档。

## 风险、不变量与预算

关联ADR0004/0007/0008/0012/0013；固定视图、稳定ID/version、唯一源、质量与资源预算不变。
plan按完整差异要求contracts、functional、harness-tests、performance-smoke、policy、repository、rust、stability-component。`affected_modules`为空不代表无风险：共享M0 Lab和归档器影响各验收driver，必须运行组合代码。

合同固定seed17/16维、256行起点、16行append，定时窗口8次更新至384行；延迟<=10000ms、协调器及各worker已采样RSS<=512MiB、P0 ANN recall@10=1。10000行/32批/128 run限制及既有M0/M1/M2基准未改变。媒体0、缓存不受控等缺口单列，不宣称提速。

## 验证与恢复

所有heavy命令及提交hook在共同Git目录 `guradb/coordination/a0-heavy-gates.lock` 的fcntl.flock内串行执行，锁覆盖整个子进程树。主线check/pre-commit自动使用原始task base；提交后显式 `check --base d95d1ada607fe40a6b1cf8eb19773b3a10f95bae`。

最终原始审计逐文件核对v2 manifest与命令日志摘要、result的commit/checkout、M0全部容器成功采集receipt、P0输入/查询/合同摘要及请求响应对应；独立源oracle重放每个响应，窗口各段均有读/append/publish。最终 `task-finish --report ... --review ...` 再校验报告并归档。

没有业务数据或生产持久协议迁移。新M0 result附加证据协议字段；旧格式只用于保全，不改绑身份。失败保留日志/diff/原始目录；两次无新证据失败先定位，需恢复时用上述checkpoint在新目录恢复，代码恢复不删除归档或抵消外部副作用。

## 复核与剩余风险

独立复核发现并修复容器删除早于日志采集、停止失败未核对运行状态、运行目录并发复用，以及JSON整数键往返摘要不一致。集成文档与组合代码另做独立只读审查。

历史14份M0日志不可恢复；旧P0整数键摘要归档保持原样。训练真值覆盖manifest，实际Parquet独立逐值比对留给A1；最新view选择时刻未独立认证。完整缓存/成本/故障/长稳、多机、远端CI和发布均未通过。结果、命令、报告及后续进入条件见[集成复核](../reviews/2026-10-18-a0-integration.md)。
