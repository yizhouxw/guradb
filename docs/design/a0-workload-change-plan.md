# A0 独立真值与负载节奏变更计划

状态：组件合同已实现并完成独立复核；最终 commit 绑定的运行与门禁见任务 receipt。
仅本地 synthetic 组件合同，不是 A4 或发布验收。

起点 `d95d1ada607fe40a6b1cf8eb19773b3a10f95bae`，分支
`codex/a0-independent-workload`，独立 worktree
`/Users/chad/.codex/worktrees/a0-independent-workload/guradb`，起点干净。
恢复点 `checkpoints/20261018T102207Z-before-a0-independent-workload-567393a5`。
任务 `a0-independent-workload`；不修改 main，不推送；最终合入由集成会话负责。

## 可观察验收与范围

对应[下一阶段 A0](../plans/2026-10-18-next-stage.md)，遵循 ADR 0008、0012、0013
及[身份/版本合同](../product/data-contracts.md)。P0 全文、RRF、训练结果由源输入建立
独立真值，禁止以生产 search/samples_for 的结果作为预期。固定输入、seed、查询、
预算和时点；定时负载每个四分位都有更新与读取，超时或只在开头写入必须失败。
保留已有六类请求，增加过滤/NULL 验证，拒绝重复键、样本漏重和旧记录版本漂移。

白名单仍为本机托管 append、Iceberg v2、16维 squared-L2、ASCII BM25-v2、
三 worker、固定视图训练与一跳图。拒绝源修改/删除/schema演进、跨机 writer、公开写入。
不修改执行器、支持发现、M0 driver、harness policy/workloads 或共同归档实现。
不建立业务 baseline，不提前实现 A1–A6。

## 风险、不变量与预算

plan 对 scripts/tests/docs 选择 contracts、harness-tests、policy、repository；
无生产模块变更。额外手动运行真实 P0 local/HTTP/60秒 driver，以弥补默认路径选择
不运行 runtime suites 的限制。重点覆盖同视图 ID/version、旧行版本继承、过滤后全局
BM25、候选窗口后 RRF、训练完整性和全局资源预算。

预冻结：初始256行、append16行、timed8次（384行/9个源文件），非定时保留调用者
updates（1..8）；不突破 writer32批/10000行及目录128 run。查询<=10000ms、
coordinator/每worker RSS<=512MiB、top_k10/candidates100、ANN4分区/4probe
保持完全精确 Top10 对照。首次结果只作为候选；没有冷缓存或完整资源指标时显式缺失。

## 实施与故障断言

1. 标准库 oracle 从固定源行/向量、明确 context/revision 生成独立预期；小型手工fixture
   验证公式与编码，突变排序/过滤/版本/漏重必须失败。
2. 绝对时点调度、真实 append/publish/request trace；迟到不集中补跑，窗口不足拒绝。
3. 结果保存输入、查询摘要、原始响应、成本和构建/历史大小，并沿既有 trace/log 归档。
4. 轻量测试、真实受锁 P0 运行、独立复核、提交前/提交后原始 base check、task-finish。

重型命令及 pre-commit 持有共同 Git 管理目录
`guradb/coordination/a0-heavy-gates.lock` 的 fcntl.flock，覆盖全部子进程。
不删除其他会话资源。失败保留 artifacts；相同条件两次失败无新证据先定位根因。
没有持久协议变更或迁移；测试只创建隔离数据。恢复代码不清理其他实验/业务数据。

## 结果与剩余事项

最终实际命令、独立复核、报告、commit/checkpoint 由本次任务 receipt 与交付说明记录。
独立复核发现并修复：主线程失败先取消后台调度再等待线程池；响应必须绑定受理句柄视图；
新增源记录不能复用旧revision/view。原始响应在断言前保存；新增28项轻量测试通过。
默认最新发布的选择时刻未独立认证，本片证明受理后的固定视图与源输入/身份/版本一致。
全文-v1/更大数据、多机、受控缓存矩阵、五次独立性能重复、native完整峰值内存、
稳定性 registry 和 soak 仍不在本片完成范围。组件通过不能转为完整 performance ready。
