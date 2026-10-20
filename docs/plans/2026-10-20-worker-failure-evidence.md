# 本地 worker 失败证据留存

状态：已通过本地九套门禁，远端原始worker异常原因仍待新诊断。follow-up task worker-failure-evidence；本切片base 758df5b，完整PR原始base仍为302caa9，分支codex/fix-p0-native-builds，worktree独占。关联ADR0012/0019、INV008及原P0修复计划。

最新PR检查39356393863 Python3.11的performance-smoke已通过，但functional-2的首次exact分片查询返回worker_failed；实际stderr位于TemporaryDirectory内，被finally删除。旧head的另一运行出现graph超时，尚无证据证明同因，禁止放宽预算或盲目重跑。本次先补最小诊断，保持失败门禁；不将诊断增强当作实际worker根因修复。

支持：失败时仅向原私有job目录写三片各最多8192字节日志尾部及最多三组PID/退出码（退出码为空表示采样时仍运行）。不复制task输入、环境或scope，不改变公开HTTP/CLI结果、错误码、预算、取消/清理、算法或持久事实格式，用户手册合同无变化。诊断文件不通过结果接口公开，沿原job释放；文件名固定、create-once，已有文件不覆盖，因此每job最多24KiB原始日志加小型JSON，不会按失败次数增长。

验收：真实子进程异常的stderr和退出码在临时输入清理后可取；较大stderr被截到8KiB/片；诊断磁盘错误及既有内容冲突不掩盖原错误；成功路径无诊断。保留真实功能/组件性能/故障与全覆盖门禁，原P0数据、8次更新、并发及60秒/10秒等阈值不变。

完成后单独复核、提交与提交后check/receipt，再对302caa9完整PR范围check/checkpoint后push。PR #3按当前head验收，失败时读取新日志定位，不能用旧head绿灯或本切片报告冒充全PR证据。回退走PR，日志无业务迁移/外部补偿。

本地真实异常用例还复现旧cleanup缺陷：cluster.local在子进程刚退出、macOS尚未收割时killpg返回EPERM，直接清理逻辑掩盖原错误并跳出其余子进程回收。common.process.stop_group已有对应Darwin僵尸/退出窗口的实测处理；本次复用该统一实现替代local及HTTP worker的重复killpg/wait，不吞掉持续权限错误。失败前diff保存artifacts/worker-cleanup-failure.patch，完整任务原始基点不变。

本轮实际实现还按P0计划补充全局+三分片单进程批量构建，保留四个独立Lance数据集/版本和大输入回退。`ann: null`在访问catalog前明确拒绝，避免新可选内部接口把显式不支持值当成缺省；真实四索引真值/版本测试通过。

`.venv/bin/python scripts/harness.py check` 报告artifacts/harness/20261020T022924Z-6227a3d4/report.json九套门禁通过；实际异常、8KiB日志上限、诊断磁盘失败/已存在内容不掩盖错误及进程回收负例通过。误删os import的本地单测错误已恢复，错误检查运行保留于artifacts/harness/20261020T022747Z-665f250c并明确中断，未当作通过。

独立复核轮次检查：本次诊断仅失败路径写入原job私有目录固定四个文件，最多三片8KiB原始日志及小型JSON；不留task输入或环境，不公开结果接口，Job.release原目录清理涵盖诊断。日志保存失败/内容冲突均保留原异常。复用common.stop_group维持既有严格进程组回收与持续权限错误拒绝。ANN全局与分片文件布局/身份、摘要和版本不变，四个任务仍完整执行，不缓存查询或跨视图进程；聚合输入超限退回旧单索引调用，任何失败仍不发布。源码范围和原始基点302caa9已在P0计划记录，真正CI异常原因未查明前不声称已修复。
