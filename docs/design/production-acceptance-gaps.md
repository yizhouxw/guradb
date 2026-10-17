# 生产验收缺口与执行条件

本地三个 worker 是用户确认的集成目标；本页不把本地组件测试提升为生产发布。范围权威仍为[路线图](../roadmap.md)。

| 项目 | 本地可执行入口 | 获准生产声明前必须取得的证据 |
| --- | --- | --- |
| P0 并发集成 | `.venv/bin/python scripts/p0_acceptance.py --rounds 5 --updates 8` | 同时保留每个查询视图、全量真值、worker PID、源提交/目录epoch、训练pin、失败日志 |
| 持续负载 | `.venv/bin/python scripts/p0_acceptance.py --duration 3600 --updates 8` | 这只是有界本地持续运行；目标部署的长期窗口、资源趋势、worker/协调器重启、故障及恢复trace必须另做，短跑不冒充soak |
| 完整性能 | `scripts/m2_acceptance.py performance-smoke`；按 `harness/evidence.md` 生成候选再运行 `harness.py compare-performance --baseline ... --candidate ...` | 固定环境/数据/参数；各工作负载至少5独立运行；真冷/暖/部分命中/超过总缓存，前后质量、GET/字节、RSS、构建/存储放大；首次测量不是可比较baseline |
| 完整故障 | `scripts/m0.py stability-component`、`scripts/m1_acceptance.py stability-component`、`scripts/m2_acceptance.py stability-component` | `harness/faults.toml`全部场景必须实际注入并由 `harness.py verify-stability --report ...` 校验；组件结果不得填成未运行场景 |
| 备份恢复 | `scripts/m4.py backup/verify/restore`，详见[操作](m4-local-recovery.md) | 新环境恢复所有对象/目录/pin、撤权补偿、源结果未知对账；量测RPO/RTO；跨主机对象权限/密钥和异地副本取回 |
| PG HA/PITR | 独立环境部署至少主备，配置WAL归档后使用 `pg_basebackup`/`pg_verifybackup`；按选定PG运维方案切主 | 持续写入下主库丢失、已确认提交保留、旧主fencing、还原到指定时间；本地单PG重启不证明HA |
| 多机容量/再平衡 | 当前三片按稳定键生成；新Snapshot全量重建后CAS发布 | 至少三台目标主机真实分片I/O；扩缩容迁移中不漏/重数据、旧任务fencing、预算与热片影响；负载超过总缓存 |
| 升级/回滚 | 保留旧版本bundle/pin；先离线联合备份，再用新程序重建；回滚选择旧视图 | 两个真实版本间schema/协议兼容矩阵、进行中作业、源append与未知提交对账；不得仅回退二进制宣称恢复 |
| 权限/审计/告警 | 当前HTTP操作重新授权；PG作业状态可诊断；恢复保留备份时点权限 | TLS/密钥轮换、撤权传播窗口、不可篡改审计、保留与脱敏策略、目标监控和告警触发/恢复实测 |
| CI与分发 | `.venv/bin/python scripts/harness.py check --scope release` | 当前完整performance/stability/soak仍planned，release预期失败；推送需授权并首次远端CI验证；镜像SBOM/许可证审批见[分发政策](distribution-policy.md) |

## 如何记录生产证据

每次运行创建新 artifacts 目录，记录 commit、checkout digest、依赖锁、数据清单、环境与查询参数，保留失败原始日志。外部基础设施的地址凭据只通过环境注入，不写报告。没有获准环境时明确未运行；不把配置模板、mock、重复同一报告或全量重建描述成已实测生产能力。
