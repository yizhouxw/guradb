# A0 P0 输入摘要 JSON 往返修复

状态：有限修复已实现；最终门禁与结项以任务 receipt 为准。不改变运行时或负载。

任务 `a0-input-digest-repair`，起点 `063ef1ec48674e452f1faa18a397c7a31e883572`，
分支 `codex/a0-input-digest`，独立 worktree
`/Users/chad/.codex/worktrees/a0-input-digest/guradb`，起始干净。
恢复点 `checkpoints/20261018T110218Z-before-a0-input-digest-repair-7f46828b`。

## 可观察验收与范围

当前 `inputs.vectors` 在内存中使用整数键，JSON 落盘变为字符串键，canonical 排序
随之改变，导致 `dataset_digest` 无法从归档输入重算。本片将持久向量映射的键明确
设为十进制字符串；运行时向量、源行、查询、调度、质量与资源预算均保持不变。
归档 `inputs/trace.json` 经 JSON 读取后重新 canonical/SHA-256 必须等于 result 合同
的 `dataset_digest`，local 和60秒定时合同都覆盖。

白名单仍为原 synthetic P0 组件合同；不增加生产能力、不实施 A1–A6、不改旧归档
及原始结果，也不改其他 worktree 或 main。没有业务数据迁移。

## 风险与验证

关联 ADR 0008/0012/0013 与 A0 证据可复核要求。plan 的 affected_modules 为空，
required_suites 为 contracts、harness-tests、policy、repository；runtime_changed=false。
先新增 JSON 往返回归，保留修复前失败；检查持久键类型、向量值与原生成器一致，
并保留整数键排序反例。更新固定摘要只反映 JSON 表示修复，不改变源数据。

实现差异先交独立集成审查。全部完整 check、pre-commit 与真实 P0 local/HTTP60
持共同 Git 目录 `guradb/coordination/a0-heavy-gates.lock` 的 fcntl.flock，覆盖命令
及子进程。最终 commit 运行新证据，逐文件核对 v2 manifest，再从归档重算数据集、
查询及合同摘要；提交后 check 覆盖本任务原始 base，然后 task-finish。

失败保留 artifacts；两次无新证据失败先定位根因。旧归档仅保留，不重写其摘要；
代码恢复不删除新证据。本片无性能提升声明，受控缓存、完整 RSS、独立 Parquet
真值及完整 performance/stability/soak 的既有缺口保持。

## 结果与交接

最终命令、独立复核、报告、commit 与 checkpoint 以本任务 receipt 为准；未完成
前不声明通过。只交付本分支，主线集成另行核验，不推送或部署。

修复前新增往返回归在 local/timed 两种输入均失败，保留于
`artifacts/a0-digest/before-fix.log`。修复后29项 P0 合同/oracle/schedule 单测通过，
运行时向量值与查询摘要保持不变。最终原始归档须重新核验，不能复用旧结果结项。
