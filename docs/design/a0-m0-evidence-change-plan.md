# A0 M0 原始证据保全

状态：实现、独立复核及工作区门禁完成；提交绑定检查与完成 checkpoint 见本任务 receipt。task `a0-m0-evidence`，基点 `d95d1ada607fe40a6b1cf8eb19773b3a10f95bae`，分支 `codex/a0-m0-evidence`，独立 worktree `/Users/chad/.codex/worktrees/a0-m0-evidence/guradb`，起始干净；恢复点 `checkpoints/20261018T102236Z-before-a0-m0-evidence-925c2bb6`。

## 用户验收与范围

M0 三类成功运行保存 result、trace、构建日志和全部已创建容器日志到共同 Git 目录的 `guradb/m0-evidence/v2/<内容摘要>/`，顶层命令输出可定位该归档。缺件、trace 摘要不符、损坏旧归档失败且保留现场；完全重复不覆盖，同结果不同 trace/log 为不同身份，并发只发布完整归档。旧 `4de2fde7` 三组证据与已归档顶层报告/命令日志核对后按原字节保全，原 artifacts 不删除；不将其计作当前 commit 的运行结果。

支持：现有 M0 functional/performance-smoke/stability-component，兼容旧结果没有 build 日志摘要的格式。拒绝不完整、symlink、摘要不符、已存在的运行目录（原子创建避免并发复用）以及运行中代码身份变化。fixture 保持原入口。非目标：能力扩展、A1–A6、阈值/依赖修改、业务数据迁移或清理、远端动作。

## 风险与不变量

复用 v2 全文件内容寻址、锁与原子发布；M0 校验针对同一待归档字节快照，避免校验与归档分别读取造成不一致。可选校验回调不改变 M1/M2/P0/local 行为。关联 ADR 0007/0008/0010；此变更为证据完整性，不改变查询结果、授权、发布或存储预算。自动 plan 要求 contracts、functional、harness-tests、performance-smoke、policy、repository、rust、stability-component。

## 实现与验证合同

先以独立 synthetic 字节验证缺 result/trace/容器日志、摘要不符、旧目标损坏、相同结果不同 trace/log、重复与跨进程竞争；驱动单测验证失败退出及现场。模拟证据不证明数据库质量。真实套件保持全部现有输入/断言/预算，串行在共同 Git 管理目录 `guradb/coordination/a0-heavy-gates.lock` 的 fcntl 锁内运行，包括 hook。各 worktree 独立 venv/输出，不共享可写 target。

归档只复制受控 result/trace/log，排除 auth、server 配置和数据。构建/执行/归档异常保留 failure 及已有输出，不伪造成功。失败现场保留；两次无新证据失败后定位根因。v2 新增 m0 family，旧归档不迁移或覆盖；代码恢复不删除新增归档，磁盘故障/异地备份仍未覆盖。

## 结果与复核

最终实际报告、commit、复核、checkpoint 由 task receipt 记录；主线集成独立覆盖三个 A0 切片的原始范围。当前尚未宣称门禁通过。

## 独立复核发现与历史保全结果

旧三组已逐字节保全，原 commit `4de2fde7faf04b640ae8dbe02022e78e94db59ee`、checkout digest `147a1624fae4b814878d797ea84f2ec3712313cf157c4ea3191c2540334daf3e` 保持不变。顶层报告 `d032a1095c8e95d5ffae0b590ce687f2542ab8035fb7314f13cdef7b6ce626a7` → 命令日志 → result → trace 摘要链及该历史 commit 的 Cargo.lock 已核对。归档根为共同 Git 目录 `guradb/m0-evidence/v2/`：

| suite | 归档标识 | 原始文件数 |
| --- | --- | --- |
| functional | `71ff0fb7fb1d7e56f9e8f19a33bfc81fb2a9a161645f620e0f2456310d616a06` | 13 |
| performance-smoke | `ea196ef099d96d2e23f3dbf398ec7b22d3b3ce87c35ef3cb32990cdbdab304fe` | 8 |
| stability-component | `6f03b55ed72ba946aff65d607fe38398c7e1c58afba01b8c6a214a30037d5a64` | 6 |

历史限制：容器日志此前没有独立摘要锚点，21份中14份仅含 Docker `No such container` 错误（functional 8、performance 4、stability 2）。它们按现存原字节归档，不能恢复已删除容器输出，也不能把归档视为补齐历史日志。原 artifacts 保留。一次性核对脚本与保全 receipt 在此 worktree `artifacts/a0-m0/`。

独立审计定位到 restart 先删容器、close 才收日志。修复在移除前停止并提取日志，成功后才移除；失败保留容器和诊断，不覆盖已有日志。新结果声明 `container_log_protocol=1`，逐容器提取成功状态、集合与摘要写入 trace 并核验；旧无标记格式仅兼容历史保全。新增负例覆盖非零、timeout、空成功日志、重复close、缺采集receipt与运行中代码变化。


修复版完整检查：`artifacts/harness/20261018T103735Z-6acbb15a/report.json` 的8项所需 suites 全通过，M0新归档逐文件及commit/digest核验一致，21个容器全部有成功采集receipt。12项M0负例/驱动单测和通用归档7项已通过；独立复核提出的先删除后采集、停止失败未确认两项均已修复，并用原子目录创建阻止并发driver复用现场。首轮 `20261018T102436Z-e9c3faad` 仅为修复前诊断，不作为最终日志完整性证明。完整 performance/stability/soak 仍 planned；本片不声称发布通过。最终提交后的检查覆盖 task 原始 base，具体 commit/报告/checkpoint 以 receipt 为准。
