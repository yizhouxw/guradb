# 本地三 worker HTTP 传输合同

状态：实现中；local-p0-integration附加切片，base 0b3af06，共享worktree不独立提交。

验收：三个独立HTTP服务进程接收固定query.worker任务，HMAC认证请求与响应，任务身份绑定协调器owner/授权scope/分片/视图及输入摘要；SQLite持久去重，重复完成任务仅返回缓存结果，运行中重复返回operation_busy，owner冲突拒绝；服务重启不重试未知运行任务。过期/取消任务不得发布迟到结果，取消杀进程组并收割；请求和响应分别累计32MiB，沿用总deadline及512MiB执行进程RSS。

支持白名单：明确IPv4 loopback HTTP地址，可信单主机共享文件系统中的绝对路径，单个固定worker模块，三个endpoint，每服务最多两个执行任务。拒绝非loopback、URL凭据/路径/query、任意module/command、过期请求、无效HMAC、越界文件路径。HMAC密钥通过环境提供，不进payload/log。没有跨机器TLS、对象传输、服务发现、HA、授权撤销广播，不能用此模式部署生产。协调器仍须在调用前及发布时检查授权/pin。

任务协议使用UTC expires_at跨进程传deadline，server转换本机monotonic；cancel独立请求只允许原owner；去重目录在root内持久保存请求摘要/状态/有界响应，无事实层写入。中断恢复保持running任务为abandoned，禁止自动执行；完成任务仅在原deadline内重取，返回expired即整项失败。

风险：INV001/003-012；plan要求contracts/functional/harness-tests/performance-smoke/policy/python/repository/stability-component。测试须使用三个真实服务进程、HMAC负例、owner冲突、持久重放、deadline/取消与响应限额。全套门禁与独立复核由主任务执行，非跨机器证据。

实现与审查补充：SQLite记录包含expires，入站请求清理已过期且非running记录，最多128条未过期/运行记录及128MiB缓存响应；非existent task的cancel tombstone保持30秒（最大任务TTL），避免先取消后到达的任务重新启动。旧schema自动加expires并保留30秒兼容窗口；原expires_at已过的任务无论缓存存在与否都拒绝。server task目录由进程flock独占。

路径scope只检查固定artifact descriptor及source_files拼接结果，不解析业务values中的path/root列。HTTP accept阶段最多4连接，解析header前设置2秒socket等待界限，最多2执行任务；客户端用绝对monotonic deadline watchdog主动shutdown socket，body read1分块复验，取消并行发往3服务，所有本地请求线程和watchdog必须join，不留后台请求。协调器将输入envelope合计限制32MiB，响应每片保守分配总限额的三分之一，并合并worker预算计数。

服务只启动固定remote_runner入口，入口在导入query.worker前监测父PID；父亡时先中断Python以触发native子任务finally回收，0.5秒仍未退出则回收其后代进程组并结束自身组。SIGTERM正常服务停止先取消active再等待handlers收割；SIGKILL恢复把真实running任务标记abandoned，绝不自动重试。

验证命令：`.venv/bin/python -m unittest tests.contracts.test_transport -v`。包含真实3服务/3执行进程、持久完成缓存重放、实际服务SIGKILL+FIFO阻塞执行进程消失和重启拒绝、运行中重复拒绝/取消收割、HMAC/owner/过期/越界拒绝、140条已过TTL记录回收、业务path/root合法列、慢远端取消/滴字节绝对deadline、未完整HTTP header连接准入、超响应声明长度。FIFO仅故障fixture，不构成生产共享文件系统支持承诺；跨机TLS/对象传输仍拒绝。

SIGKILL scratch恢复：新服务持有task root独占lease后，对严格`task-[a-z0-9_]{8}`自有目录做有界清理（最多128个，拒绝symlink/非目录）；存在遗留时先给固定runner父亡清理0.6秒窗口。真实崩溃测试重启后同时断言无旧task-*目录；目录中没有凭据，任务不因残留文件重新执行。

## 操作入口

三个worker分别使用不同目录/端口，`--shared-root`指向包含已发布构建产物的同一本机目录。密钥由操作者安全设置到`GURADB_WORKER_SECRET`（至少32字节）；不要写进命令参数或报告。

```sh
.venv/bin/python scripts/worker.py --root data/worker-1 --shared-root data --port 8091
.venv/bin/python scripts/worker.py --root data/worker-2 --shared-root data --port 8092
.venv/bin/python scripts/worker.py --root data/worker-3 --shared-root data --port 8093
# 在另一个终端启动协调器；端点恰好三个，密钥与worker一致。
.venv/bin/python scripts/m1.py --root data/serving serve --workers 3 \
  --worker-endpoint http://127.0.0.1:8091 \
  --worker-endpoint http://127.0.0.1:8092 \
  --worker-endpoint http://127.0.0.1:8093
.venv/bin/python scripts/p0_acceptance.py --transport http --duration 60
```

独立命令需在不同终端保持运行，端点模式不自动启动服务。最后一条验收命令会自行创建临时PG和三个worker，运行后清理进程。
