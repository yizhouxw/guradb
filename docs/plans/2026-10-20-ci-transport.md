# CI transport 合同测试修复

状态：进行中。任务 fix-github-actions；起点 main / fe0a70c8a6d8451acaa21e160a5adde0c0c8e2f2，工作分支 codex/fix-github-actions，独立 worktree /Users/chad/.codex/worktrees/fix-github-actions/guradb。起始树干净，恢复点由 task-start 建立。

## 范围与验收

修复 Actions 39346612127 中 Python 3.11/3.14 contracts 失败，保留所有门禁、负例、连接数与超时预算。支持白名单：调整测试连接建立/观察顺序及资源清理；拒绝通过重试整个测试、扩大超时/队列/连接上限或跳过门禁变绿。不改变数据库行为、API、配置、持久格式或依赖，因此无用户手册行为变更。关联 ADR 0007/0008/0016。

失败产物保存在 artifacts/failed-ci；Python 3.14 的 test_incomplete_headers_have_connection_admission_budget 在十连接列表构造阶段 socket.create_connection(timeout=1) 超时，未进入预算断言或 finally，留下未关闭 socket。当前 macOS 原树门禁通过，说明不能用本机通过代替 Linux 证据。

## 风险、不变量与方案

串行发起十个不完整请求，每个完成一次存活/拒绝观察后再继续，避免未被 accept 的连接同时挤占内核 listen backlog。保留最多四个存活连接的原断言，使用 ExitStack 在任何连接/发送/断言异常时清理已创建 socket。生产 admission、header timeout、连接上限及 INV 资源预算不变。plan 选择 contracts/harness-tests/policy/repository/unit-coverage；不修改性能基线或门禁。

## 验证与恢复

保留真实 loopback worker 负例，运行 Linux 单测、完整本地 change 门禁和独立差异复核；提交后对原始 base 重查并 task-finish，快进 main 后绑定主线报告/checkpoint，再推送检查双 Python Actions。完整 performance/stability/soak planned 状态不属于本次发布证明。回退使用新的 revert 提交；无数据或外部业务副作用。

## 结果

待记录实际报告、复核发现与远端状态。历史 Actions 39181666400 另有 unit-coverage/performance-smoke 失败，需检查证据区分是否同因或仍存风险，不以本次选定范围成功宣称历史全量问题均解决。

2026-10-20 实测：Linux python:3.12.12-slim-bookworm 原测试在连接阶段复现 TimeoutError（artifacts/linux-before/transport.log）；修复后同容器单测通过。容器仅覆盖挂载将 semaphore 改为 10 的反向实验按预期得到 `10 not less than or equal to 4`（artifacts/linux-after/mutation.log），生产源码未改。

本地 `.venv/bin/python scripts/harness.py check` 报告 artifacts/harness/20261020T002109Z-45fcff09/report.json 五套门禁通过，contracts 109 / harness 94，unit-coverage 包含 Python/Rust。独立复核轮次确认十次连接、1秒connect、0.03秒观察和最多四个连接断言保持，ExitStack覆盖列表构造失败时原先遗漏的资源清理；没有放宽预算、扩大服务backlog或修改生产实现。无额外发现。

历史39181666400的unit-coverage失败也是同一连接TimeoutError，Python/Rust覆盖率均达原门槛。另一次P0持续负载的末次发布实测60.219秒超出60秒窗口；本次原命令 `.venv/bin/python scripts/p0_acceptance.py --transport http --duration 60 --run-dir artifacts/p0-ci-diagnostic` 通过，报告 artifacts/p0-ci-diagnostic/result.json。未修改该负载、窗口或阈值，单次本地通过不消除共享runner性能波动风险，也不宣称完整发布通过。

后续以提交后的task receipt及主线checkpoint绑定最终commit和报告，远端双Python结果以对应Actions运行记录为准。
