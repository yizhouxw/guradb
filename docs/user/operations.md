# 运维管理

当前仅面向可信操作者的本地受控 alpha。以下要求用于减少评估现场的数据和权限风险，不代表已有生产 HA、在线迁移、PITR、审计或告警系统。

## 配置与权限

| 服务 | 配置/身份来源 | 生效与边界 |
| --- | --- | --- |
| M0 | server.json 中 listen、manifests 路径及摘要、auth_file、可选 pg_listen/limits | 配置/清单启动时绑定，换清单须重启；auth_file 在请求/执行/取结果时复查 |
| M1/M2 | `GURADB_PG_DSN`、`--root`、PG dataset/grant、`GURADB_TOKEN` | root 必须与构建产物一致；控制面 DSN 不给客户端；CLI 仅通过 HTTP |
| HTTP worker | 各自 `--root`、共同 `--shared-root`、loopback 端点、`GURADB_WORKER_SECRET` | 三个端点，共享本机文件；密钥至少 32 字节，不写入任务或日志 |

M0 auth_file 保存 token SHA-256、tenant/principal 和 dataset UUID allowlist，原始 token 由客户端保管。更新授权时同目录写完整临时文件、校验后原子 rename，设置文件权限；不要原地 truncate。文件无效时 fail closed，PG 可能返回 58000。M1 使用内部目录 grant，不能假设 M0 token 文件授权会自动传播到 M1。

服务默认受控 loopback；M0 示例容器内部监听 0.0.0.0，但宿主只发布 loopback。没有内建 TLS/OIDC，不开放公网；PG wire 本片强制本机 loopback。外部代理、安全身份与跨机方案需独立设计验收。

## 构建、刷新与发布

1. 记录 dataset、源 snapshot/metadata 摘要、operation 和产物 root。先 snapshot；只有已验证完整 append 历史且旧文件身份匹配时才使用 refresh。
2. 通过 `scripts/m1.py progress RUN_UUID` 观察 discovered/applied/indexed/published；ready 只是可发布候选。
3. 用 `publish RUN_UUID --expected-epoch N` 执行 CAS，N 来自当前目录状态，首次为 0。冲突时重新读取并判断，不能无条件覆盖指针。
4. 用 describe 及真实查询核对 read_context/版本和结果。源已提交、索引构建成功与对外发布分别确认。

命令前置与参数见[M1](../design/m1-running.md)和[M2](../design/m2-running.md)。超时/断连等提交结果未知时先查原 run/operation；同 operation 不换 target。托管 append 只允许可信单机独占目录，不能靠换 operation 名称盲目重放。

## 查询、保留和 GC

训练消费期间保持 pin；人工消费者用 `pin RUN_UUID --owner NAME`，消费结束再同 owner unpin。M0 若读取某个 M1 生成 manifest，启动前人工 pin，停止后释放，它不会自动跟随目录或持有 M1 job pin。

`gc OLD_RUN_UUID` 仅处理工具生成的旧 run，拒绝当前 published 或任何 pin；不删除外部源湖。先查询 pin、训练消费与源引用，再在正确 root 上执行。不能直接删数据目录来绕过 GC。PG 历史 run 上限 128，当前没有通用历史清理能力；达到准入上限应停止新增并规划迁移。

M0 重启清空内存 job/结果/游标；M1 重启时遗留非终态 job 可明确失败，不透明重放。多个协调器实例不能共享单进程 lease；PG 重启导致连接失效后需要重启服务并对账旧 job。

## 状态和诊断

```sh
# DSN 通过受保护环境预先注入
.venv/bin/python scripts/inspect_state.py
```

预期输出 dataset generation/epoch、run 进度、job 类型/状态/错误聚合、pin/grant 计数及 managed intent 状态。这是单个 repeatable-read 只读事务的当前状态快照，不是完整历史或不可篡改安全审计。保存统计、commit、配置摘要与故障 trace，避免保存凭据或业务值。

没有经验证的产品吞吐/延迟 SLO；按容量硬上限控制评估负载，性能报告区分冷/热、请求、字节、内存和质量。具体排错见[诊断指南](diagnostics.md)。

## 备份、恢复与升级

备份前停止协调器、worker、托管 writer 和其它消费者，确认没有仍在写的作业；按[本地联合恢复设计](../design/m4-local-recovery.md)取得 PG 目录及完整 root（事实、特征、媒体、索引、训练输出）的一致副本。记录备份时点、版本和 pin；恢复后对账备份后撤权，不能让旧备份重新开放已撤销权限。当前无在线一致备份/HA/PITR 承诺。

派生索引丢失而事实副本完整时，用 `rebuild-indexes --dataset UUID --operation NAME` 创建新 ready run，再独立 CAS publish；不原地修补 published bundle。它保留数据/记录版本而更新视图/索引版本。事实或 manifest/媒体摘要损坏先恢复备份，重建不能补回缺失事实，详见[重建操作](../design/m2-index-rebuild.md)。

升级前记录 reader/writer、bundle 版本、进行中 job/pin、备份点和兼容窗口。bundle v2 不保证旧 binary 可读，旧 v1/v2 BM25 数值也可能不同；先排空新类型 job，保留可读旧 view，再按对应切片的回滚说明操作。停用 PG wire 删除 pg_listen 并重启，回退旧 binary 前也需移除未知配置字段。Git revert/checkpoint 不能撤销数据迁移或外部副作用。
