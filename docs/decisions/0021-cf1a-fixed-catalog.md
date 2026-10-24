# ADR 0021：CF1-A 固定目录的独立持久布局与计划发布

- 日期：2026-10-21
- 状态：提案，待实现、独立复核与真实 PG 验证
- 关联：ADR0004/0016/0019/0020、[变更计划](../design/fixed-catalog-change-plan.md)、[用户合同](../user/fixed-catalog.md)

## 问题与取舍

现有 `gura_m1` 目录没有 CF1-A 的完整 immutable target、当前 policy tombstone epoch、精确 lease 和 bind 响应丢失重试身份。直接 JSON 包装旧接口会保留不同授权/版本语义。仅 generation CAS 也不能区分主动新计划与旧 worker 刷新 CAS 后晚发布。

选择新增 versioned `gura_cf1a` 元数据 schema，与 legacy 并存而不双写。canonical bytes 用 bytea 加 SHA/受验证 lookup 列，保持 A 的字符串与整型域；不依赖 PG JSONB 的文本域或重序列化。代价是读取时严格 decode/hash/lookup 交叉核对，以及后续显式身份保持迁移。

## 拟议决定

1. 特权 provision globally nonreusable dataset ID 和 immutable tenant；同一 dataset 行锁序列化目录变更、授权、query lease 和 reconcile，无缺行锁假设。
2. data head 与 active publication plan 分离。首片仅 prebuilt complete target；g→register g+1→publish g+2，完整 T/hash 不变、两步不同 op ID。publish 不补 artifact，也不能以新 CAS/op/sequence 复活 superseded/fenced 计划。
3. 新 revision 仅当前 head 线性后继；同 head 重建保持 revision bytes/parents，新 view/新内容 artifact 用新身份。可信 operator 拥有 register，worker publish delegation 仅一个精确计划。源提交 fencing 仍由后续源合同承担。
4. effect 与 terminal receipt 原子提交；unknown 先 reconcile，同锁 rejected tombstone 排除迟到原请求。没有 durable owner claim 时 absent terminalization 仅可信管理员加 reconcile 和原 register/publish action；管理员角色不覆盖live grant。重放原 receipt 不重新执行 effect。
5. bind 原子授权/固定 view/新 lease，持久 query fingerprint 与 issued binding bytes；丢响应重试保持原 view，过期/释放 ID 不复活。dataset policy epoch 的授予/撤销均单调推进；精确 owner/cleanup release 在读授权过期后仍可执行。
6. 首片行数/8MiB元数据容量与30秒读scope有界且显式拒绝未覆盖生命周期；query容量包含所有live/released/expired身份，已知重放/精确清理不新增身份计数。不得删tombstone、扩大quota或改A TTL以通过验证。锁定Psycopg公开非阻塞pq与Connection wait适配必须真实证明全程deadline，不能用connect_timeout最低2秒或server statement_timeout替代客户端总期限；首片仅本机IPv4无TLS。
7. provision/grant/revoke/rotate_owner 同样以稳定op、private immutable AdminIntent/frozen AdminResult实现effect与result原子提交，共享512回执/8MiB配额。已知replay不重复effect；absent admin_status只unknown，原op在同dataset/global-provision锁下可幂等重试，不能以换op或absent猜测未发生。管理值不扩A schema，也不伪造A注册意图。

## 兼容、恢复与验证

无自动 legacy import/pointer 切换、业务数据迁移、源 writer/GC、训练 pin、HA/PITR。回退关闭 adapter 并保留新表、回执、lease/tombstone；unknown 与外部保护/撤权另行对账。PG restart 验证不等于联合备份恢复；本片不检测stale restore，操作者恢复旧备份时须quarantine并停用整个adapter含mutation，外部恢复fence/对账留待P18，不能把手册义务写成已实现检测。

独立 PG18 连接/SQL 真值、提交边界响应丢失、迟到请求/对账竞争、旧计划刷新 CAS、当前撤权、canonical bytes 和持久 restart 等证据按[场景映射](../design/fixed-catalog-scenarios.md)验收。尚无本片通过结果，提案不能作为已支持功能。
