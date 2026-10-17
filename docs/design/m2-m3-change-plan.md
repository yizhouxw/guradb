# 变更计划：有界 P0 与本地三 worker

状态：进行中，不能视为 M2/M3 完成或生产发布。

## 验收与范围

用户要求完整实现项目，确认最终目标为本地三 worker 集成验证，生产验收明确保留缺口。
起点 `dba9098927ecb96451b49266cb708886db529f90`，原分支 main 干净；隔离 worktree 为
`/Users/chad/.codex/worktrees/guradb-implementation/guradb`，分支 `codex/complete-implementation`。
任务 `m2-foundations`，checkpoint `checkpoints/20261017T113134Z-before-m2-foundations-72deb242`。

按路线图分别实现 Graph 一跳、append-only 显式刷新、Lance 派生 ANN、托管 append、MCP 和本地真实进程执行。
每片先冻结契约再测试；尚未实现者继续明确拒绝，不以模块存在认定支持。
保留 M0/M1 现有边界，不引入 OLTP、无界图、更新删除、全 PG 或任意外部 writer。

## 不变量与预算

对应 ADR 0004/0006/0007/0008/0011 和 INV-001 至 INV-012 中受影响义务。
固定 view、稳定逻辑键、版本与不可变产物；源提交与目录发布分别 fencing；撤权重新检查；query/train pin 与 GC 排他。
现有上限 10000 行、32 源文件、32 MiB 源读取、128 MiB 产物读取、10 秒 query、2 MiB JSON result 保持。
Graph 最多一跳、1000 条返回边、单 seed 1000 fanout，超限失败；ANN 候选最多 1000、精确重排与独立 exact recall 测量。
本地 worker 限制为 3 个真实子进程；任务超时/退出明确失败，不承诺跨机器 HA/透明查询恢复。

## 实施和验证

每个能力分别编写设计、白名单、独立真值与负例。新 Lance 依赖固定版本并记录许可；现有 M1 产物兼容，ANN 为可选派生索引。
先局部测试，再真实 PG/S3/HTTP 功能、组件性能和故障，最后 harness 全任务基点检查及独立审查。
性能预先预算：8192 行、固定 seed；build <=60 秒，query <=10 秒，RSS <=512 MiB，记录冷进程/暖进程（不声称清除 OS cache）、请求/字节及 recall。
Graph 与精确查询要求结果完全一致；ANN 固定工作负载 recall@10 >=0.95，未满足不得宣称完成。

## 恢复和未决项

持久变化使用新独立表/版本化派生产物；旧 reader 不接受新能力时明确拒绝。保留旧 bundle/read view 和 pin，恢复代码不撤销源 append。
未知提交先按 operation ID/父版本/快照对账。失败现场和测量置 artifacts，禁止改预算过门禁。
生产 HA、长稳、升级、容量/重平衡与远端 CI 需独立环境证据，当前不承诺已验收；不推送远端。
各片实际报告、审查发现、最终 commit 与 checkpoint 在结束时填写。

## 集成复核与剩余范围

实现及独立复核完成，最终门禁/commit以task receipt为准。第一轮完整报告
`artifacts/harness/20261017T114002Z-60b12ad4/report.json`：8类通过，harness-tests因CI总作业时长不足失败，未作为成功证据。
新增driver使CI最坏串行时间增加，保持原组件阈值，更新总job预算并通过对应自测。
依赖检查发现NumPy2.5.4要求Python>=3.12，替换为同时支持3.11/3.14的2.3.5并重新验证。
独立审查修复Lance native调用期间取消、源提交未知的前置对账和固定幂等metadata、累计写入字节上限；补worker RSS、异目录启动、查询/训练与新发布竞争、MCP完整job生命周期。
托管append→ANN Snapshot→显式refresh→三worker scan/export已纳入同一个真实PG/HTTP功能driver。

本轮仍非完整项目交付：增量为全量重建，ANN/全文尚未跨worker分片、数据大于缓存/真正冷热对象测量缺失；远端worker、spill/通用exchange、容量重平衡与生产HA/长稳/升级未完成。不得将本轮task完成等同于路线图M2/M3/M4完成。
