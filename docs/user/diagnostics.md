# 诊断指南

先确定访问的是 M0 HTTP/PG SQL，还是 M1/M2 HTTP job 服务；内部 PostgreSQL 仅为控制面。保存失败时刻、源码 commit、配置摘要、dataset/run/job/query id、read_context 与错误码，随后按表定位。不记录原始 token、DSN 密码、业务参数或完整业务行。

| 症状 | 首先检查 | 下一步与恢复边界 |
| --- | --- | --- |
| Docker/构建失败 | daemon、镜像可取性、锁文件、build.log | 固定工具链下定位环境/依赖失败；不跳锁或写“已通过” |
| HTTP 连不上 | 服务进程、M0 8080/M1 8081、宿主 loopback 映射 | 看本次容器日志；不要为排错暴露公网 |
| PG 连不上 | 是否启用 pg_listen、容器内部 loopback | 客户端共享网络命名空间；普通 -p 无法转发内部 loopback |
| 认证失败/权限不可见 | 原始 token、principal、dataset allowlist/grant、数据库 guradb | M0 与 M1 身份来源独立；PG 密码不是 token_sha256；授权无效会关闭访问 |
| PG 0A000/事务或目录错误 | autocommit、白名单、SDK 自动 SHOW/SET/目录探测 | 启用 autocommit，停用不支持探测；不忽略错误宣称 ORM 兼容 |
| PG 58000 | auth_file 是否完整可读、原子替换 | 修复受保护文件；不能靠旧授权缓存继续访问 |
| 查询超时/资源错误 | 扫描、解码、行数、结果、并发和 deadline | 缩小实际输入或按后续切片扩展；不能抬门禁预算掩盖回归 |
| 句柄/游标 404 或无效 | TTL、重启、身份、query id、cursor 是否混用 | 旧句柄不能恢复；确认视图后重新查询，不拼接不同视图结果 |
| 数据摘要/文件错误 | manifest 固定 SHA、文件长度/版本、挂载绝对路径 | 恢复正确对象/备份；不重算摘要掩盖意外修改 |
| append/refresh 被拒绝 | 历史完整性、旧文件身份、是否存在 update/delete/rewrite | 重新评估支持范围，必要时显式全量 snapshot；不伪装 append |
| 已构建但查不到新数据 | ready/published、expected_epoch、客户端路径 | CAS 发布后核对 read_context；M0 不自动跟随 M1 发布 |
| publish 冲突/结果未知 | 原 run/operation 当前状态、generation/epoch | 先对账；不盲目覆盖，不换 operation 重发已提交写 |
| ANN 失败/质量不足 | 是否构建 ANN、行数、维数/模型、nprobes/候选预算 | 独立精确真值比较；小分片精确回退不等于 ANN 加速证据 |
| worker 超时/认证失败 | 三端点/各自目录、共享 root、secret 一致、deadline | 日志定位 HMAC/路径/预算；服务重启不自动重试未知任务 |
| 重启后 job 失败 | PG 连接/lease、非终态 job | 接受明确失败并核对副作用，不能假设透明续跑 |
| GC 拒绝/磁盘压力 | published 指针、pin、训练结果消费、128-run 上限 | 完成消费再 release/unpin；不要绕过 GC 手动删目录 |
| 索引文件丢失 | 事实/媒体/manifest 摘要是否完整 | 完整事实可重建新 run 后 CAS；事实损坏先恢复备份 |

PG 常用 SQLSTATE：28P01 认证、3D000 数据库、42501 权限/不可见资源、0A000 不支持、22023 参数、42P18 参数类型、08P01 协议、53300 连接容量、54000 预算、57014 取消/超时。错误恢复细节见[PG 指南](../design/pg-wire-running.md)。结果发送途中断开时应丢弃连接和不完整结果，不能当作成功。

## 取证和复现

```sh
.venv/bin/python scripts/harness.py task-status
.venv/bin/python scripts/harness.py git-status
# M1/M2，只读状态快照，DSN 从受保护环境读取
.venv/bin/python scripts/inspect_state.py
```

harness 日志在 `artifacts/harness/<run>/`；直接组件驱动按其输出路径保存结果/trace。M0 可用 `scripts/m0.py functional`，M1/M2 分别用 `scripts/m1_acceptance.py functional`、`scripts/m2_acceptance.py functional` 复现合成场景；这些命令需要 Docker/依赖，会启动自己的测试资源。不要把当前状态快照当完整审计历史。

首次失败保留命令、脱敏输入/seed、错误分类、版本与日志；再次尝试需有新假设。两次无新证据失败后停止盲试并定位根因。只清理本次 trace 明确归属的资源；恢复代码用新目录 checkpoint，恢复数据另按[运维指南](operations.md)。交接提供最小合成复现、实际/预期、相关 id、报告位置和未解决问题，避免直接打包业务数据。
