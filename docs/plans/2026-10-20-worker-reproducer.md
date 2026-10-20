# Linux worker 固定候选诊断

状态：待远端实测。owner：本次 CI 修复任务；分支 codex/worker-reproducer，独占新 worktree。原始基点949d484a3d06685d1dcd24cd8fe97a0dee375334；依赖 PR #3，诊断 PR 采用堆叠 base codex/fix-p0-native-builds，blocked-by #3。该临时分支不计划合入 main；停止实验时保留日志并 task-abandon，不把关闭 PR 视为产品交付。

范围只含新诊断 workflow、自测和本计划；既有 check.yml 无变化。无数据库用户行为、API、持久格式或迁移影响，因此不修改用户手册。共享 CI 新文件由本任务独占，现有质量门禁/预算/基线不改。

固定 checkout 到949d484，Python3.11/3.14各执行五次原始 M2 functional；每次上限900秒、INT后30秒终止，五次串行，无重试直到通过。任何一次失败使整组失败，后续采样仍保留；不改变数据、查询、真值、并发或 native 环境变量。90分钟容纳全部超时及600秒上传余量。只保留合成验收产物14天，不转储环境变量或真实用户数据。

验收是产生绑定实际源码 SHA 的五份结果或失败证据；成功采样也不能替代 PR #3 当前测试合并树的两版本质量检查。Linux worker_failed 根因仍未知，优先读取已新增的有界子进程日志/退出码；无新证据不盲改线程数/超时。诊断工作流实际执行冻结源码，不声称验证诊断分支 head 的数据库行为。

本地用 YAML 合同检查最小权限/固定 action和候选 SHA/时间预算；用真正 bash 和临时命令替身验证五次调用、一失败粘性非零退出，替身不作为数据库运行证明。运行 plan/check、差异单独复核后提交，再 check 固定原始基点和归档。远端失败保留 worktree/artifacts，无主线副作用需补偿。
