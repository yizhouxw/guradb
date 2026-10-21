# 固定版本目录组件

状态：**恢复树的局部单元、Python 严格覆盖与真实 PG 七项容量组件验收及独立复核已通过；完整仓库验收待完成**。结果绑定下文列出的运行前 34 文件清单，不代表本次文档更新后的整项任务已通过。这是供可信应用组合根嵌入的 CF1-A 目录组件合同，不是新增的 SQL、HTTP 或 CLI 用户入口。现有 alpha 操作仍按[能力白名单](features.md)执行。

## 场景和前置条件

应用已认证一个租户内的操作者，准备登记受保护的固定源及完整索引清单，发布一个 read view，再让多个操作读取同一版本。组件使用锁定的 PostgreSQL 18 镜像和 Psycopg 3.2.10，在独立的 `gura_cf1a` schema 保存元数据；首片仅认证显式 `127.0.0.1`、单端口、无 TLS 的本机 PG，拒绝 DNS/多主机/远程与未认证的连接模式。不保存业务逐行数据，也不自动导入旧 `gura_m1` 目录。

可信宿主创建 `FixedCatalog`，提供 PG DSN、当前源保护/描述符验证 authority，并为每个会话提供 `TrustedPrincipal`。此身份来自已认证的宿主，不来自传入的 JSON。`MutationAuth`、`delegation_ref` 和 pin 都不是凭据。首片的保护 authority 是操作者明确配置的可信 fixture registry；它不证明对象真的存在、索引已构建或上游已执行保留。真实源、对象和索引接线仍待 I1。

## 操作和预期

1. 可信管理员显式初始化 schema、provision 全局唯一且不可重新分配的 dataset ID，并配置 subject/delegation 的 read、register、publish、reconcile 权限及有效期。
2. 使用完整 CF1-A `ReadDescriptors` 创建 register intent。目录 generation 为 `g` 时，目标 view 预留 publication generation `g+2`。登记成功的回执为 `g+1`，但该 view 尚不能被绑定读取。
3. 使用另一个 operation ID 创建 publish intent，expected generation 为 `g+1`。发布消费同一个完整目标及其摘要，成功为 `g+2`；不会在发布时补入新的 artifact。
4. `FixedCatalog.port(principal)` 返回既有 `CatalogReadPort`。调用其 `bind(request)`，以 `published` 或显式已发布 view 创建固定 `ReadBinding` 和新 lease。之后的新发布不改变该绑定。
5. 读取和输出前调用 `reauthorize(binding)`。取消由执行 scope 处理；目录拒绝过期、撤权、伪造或已释放的绑定。结束时 `release_pin(binding)` 只释放该精确 lease；可信 owner/cleanup 在读权限过期或撤销后仍可清理。

这些名称与正常/负例在[场景映射](../design/fixed-catalog-scenarios.md)逐项管理验证义务；本轮局部结果及仍缺的验证见文末，不能据此宣布完整目录入口已交付。

## 支持与拒绝

首片仅登记预先固定且可信保护 authority 接受的完整目标。首次 revision 无 parent；新 revision 必须是当前 data head 的线性后继。同 head 的显式重建保留原 revision bytes/parents，使用新 view 或新 artifact 身份；不同内容不能覆盖已有身份。旧历史 revision 不能通过重新登记倒退成 head。旧 worker 即使刷新 CAS 数值，也不能发布已被替代或 fenced 的计划；register 仅授予可信操作者，worker 的 publish 授权还必须绑定一个已登记计划。

拒绝不兼容 schema 演进、任意 revision DAG、未发布输入的 build pin、源写入、自动 GC、训练 pin、旧目录自动迁移、跨湖事务、HA/PITR 和生产认证。已发布历史 view 的 generation 不要求等于当前目录 generation；它仍须 retained、受保护且通过当前授权。

## 权限、预算和结果未知

每个 dataset 的授权 policy epoch 单调增加，撤销后重新授予不会恢复旧绑定。首片采用 dataset 级 epoch：任一 grant 变更都使该 dataset 的旧授权 epoch 失效，其他 subject 也须重新绑定。writer owner epoch 与读权限分开，单纯交接 writer 不撤销合法旧读。

CF1-A envelope 不超过 1 MiB，查询 TTL 不超过 30 秒；等待 PG 锁、连接和 authority 验证也消耗原始 deadline，不重新起算。绑定重试必须使用原 query ID 和相同 request，仍 live 时返回原绑定；已过期或已释放的 query ID 不复活。预算或其他字段被更改的绑定被拒绝。

首片冻结 16 个 dataset；每 dataset 最多 64 个 grant、256 个不可变身份、128 个目标/view、512 个 mutation 回执、1024 个持久 query 身份（包含 live、released、expired），保存的 canonical 元数据总量不超过 8 MiB。达到行数或字节容量返回 `resource_limit`，不自动删历史或放大上限。已知回执/同 query 重放/精确 release 不新增身份数，满额时仍可执行。长期压缩/GC 属于后续生命周期合同；容量耗尽时缺乏空间的未知结果不能被伪报为已拒绝。

登记/发布的相同 operation ID 只能表示相同 intent，重放返回原回执。成功回执的 `result_id` 才表示已应用；确定的 rejected 回执不表示成功。响应丢失返回 `outcome_unknown`，先对账原 intent，不盲目重发新操作。对账与迟到请求使用同一 dataset 锁；若没有回执，只有同时持有 reconcile 和原 register/publish action 的可信管理员可写入拒绝 tombstone，阻止迟到原请求生效。管理员角色不替代 live grant。普通 reconcile/status 身份不能取消别人的操作。

丢失 bind 响应按原 query ID 重试；丢失 release 响应重放原精确 lease。两者不能用 mutation reconcile 代替。所有回执重放仍检查当前身份和授权；历史成功状态不授予数据读取权限。

COMMIT 已尝试后发生客户端中断或连接清理失败，也必须保守返回 `outcome_unknown`，按原身份对账；不能把中断当作未提交。COMMIT 前的客户端中断保持中断语义，连接关闭中止未提交事务。清理异常不能遮蔽已经未知的提交结果。

## 可信管理副作用与重试

provision、grant、revoke 和 rotate_owner 也必须提供稳定 operation ID。它们使用私有、严格闭合的 AdminIntent/AdminResult 元数据，不伪装为 CF1-A RegisterIntent。AdminIntent固定调用者 tenant/subject/delegation、dataset、动作及全部参数；同一 operation ID 不可更换动作、主体或参数。可信 administrator 只配置自己的 tenant，线协议里的 administrator 字段不能建立权限。

每个管理 effect 与完整 canonical AdminResult 同事务持久化；同 dataset 使用既有 dataset 行锁，首次 provision 使用全局 provision 锁并原子创建 dataset 和 receipt。管理 receipt 与 CF1 mutation 共用每 dataset 512 条和8MiB canonical元数据上限，不能另建无界日志。已知相同请求重放先于新 quota/CAS/effect 检查，原 revoke 的迟到重放不能再次撤销后来新 operation 的 regrant。grant/revoke 每次新 effect 推进 dataset policy epoch；rotate_owner 仅推进 writer owner epoch并 fence 当前未发布计划，读 epoch 保持。

管理响应丢失后先按原完整 intent 调用 admin_status；已有结果返回原不可变 bytes，absent 一律 outcome_unknown，不能据此断言没有发生。可在相同锁下重试**同一个不可变管理 intent**：不存在时应用一次，存在时只返回原结果。不得换新 operation ID 猜测重试。管理状态查询不会制造 absent tombstone；若原事务仍在途，同锁等待后读取确定结果或保持 unknown。初始化 version1 静态 DDL 自身幂等，不纳入管理 effect 身份日志。

## 兼容与恢复

初始化显式检查 schema version，不修改旧目录或已有用户表。CF1-A canonical bytes 用 `bytea` 加摘要保存，保持 escaped NUL、非 ASCII、完整 int8 和 typed NULL 的域；摘要不能替代源保留。

关闭新 adapter 可继续使用独立的 legacy 入口，但不会把新 pin、回执或已发布身份转换回旧格式。回退二进制不删除新表、不撤销已提交目录状态；先对账 unknown，再处理精确 lease。PG restart 的组件持久性验证不等于备份/主备/PITR。本片没有旧备份回滚的自动检测或外部恢复 fence；操作者若恢复旧 PG，必须隔离并停用整个新 adapter（包括 mutation），在外部对账完成前不能接入。该隔离是尚未自动化的操作义务，不是本片已实现的检测能力。

验收入口为 `scripts/fixed_catalog_acceptance.py --mode <functional|performance|fault> --run-dir <仓库内新目录>`，使用真实 PG 独立连接和行级状态核对。当前恢复树已运行 performance 模式；新的独立 functional、fault 模式及整项验收仍待执行。

验收证据修订的先行合同：入口须在导入生产/fixture之前固定源码身份，导入、日志提取或artifact写入失败均不得报告pass，并仍尝试清理本任务唯一命名的测试PG。日志提取失败的诊断不冒充真实服务日志；连接计数仅为成功adapter连接，失败握手与独立SQL真值连接另属边界。若证据写失败，保留可取日志/原目录并检查本次owned服务清理结果；不能据验收进程失败推断目录副作用未发生，仍按原operation/query身份对账。该修订不改变用户目录API或容量/时限，局部验证结果见文末。


首次本机真实验收在PG重启后连接阶段失败，原失败状态与原件保留。独立实验定位测试容器的动态发布端口在重启后变化；验收fixture随后显式固定一个当前空闲loopback端口并核对重启前后实际映射，发生竞争或映射异常则失败清理。该修订不改用户DSN、目录API或任何产品预算；旧冻结上的修后通过与下文本轮证据分别保存，不改写首次失败。

## 行容量补充验收的先行合同（历史记录）

旧树冻结 `c48067b5e90072dd31641cf328e115bd802b9192791cda1b316f506e36fc337c` 已有25项局部单元、229项Python测试/4028行零排除和三项真实PG driver结果；独立复核 `b68bff785afbe6f5e4788b375ecae653e3f0a80888c06326c1deee3420a02445` 只确认512条共享operation与8MiB canonical字节边界，其余行容量未被当时工作集触及。原失败及通过raw均保留，这些结果不属于当前恢复树或新增场景。

先行计划只在performance driver追加实际adapter调用与独立SQL核对：逐一达到64个grant、256个身份、128个目标和1024个query身份，最后才填满16个全局dataset。测试使用合法且彼此隔离的固定目标，避免先撞到另一配额；不直接用SQL灌入行，不改生产上限、原512operation/8MiB负载或120秒组件时限。

1024个query同时包括已释放、已过期和当前live身份。满额后相同完整request的live重放须返回原bytes；已释放或过期ID不能复活，exact lease释放不回收身份名额，新ID仍拒绝。过期等待最多1秒且计入原driver时间，不续期或扩大30秒TTL。满grant更新旧键或重放旧结果不占新行；新65号授权、257号身份、129号目标及第17个dataset必须原子拒绝，不推进epoch/generation、不遗留receipt或部分身份。该先行合同对应的实际结果如下。

## 恢复树本轮组件结果

2026-10-21 在独立恢复树、原始任务 base `4d6baca888421d90f146679ef71b0e555fe60881` 上，以运行前 34 文件清单 `2432c634478c7327786b5b42ff85aa89002c24855a56b3f217e74cde0d156955` 执行：26 项针对性单元通过，全量 Python 232 项测试通过，适用执行行 4028/4028、missing 0、excluded 0；真实 PG performance 模式通过，用时 31.526968 秒，原 120 秒上限不变。

该模式保留原 512 条共享回执及 8 MiB 字节准入工作集，另实际写入并独立 SQL 核对 64 grant、256 identity、128 target、1024 query 与 16 全局 dataset 五类行容量，共七项容量证据。满额新身份原子拒绝，已知回执或 live query 重放不增计量，expired/released query 不复活，精确清理不腾身份名额；授权已有键更新及旧结果重放也经核对。完整计数和原件入口见[场景结果](../design/fixed-catalog-scenarios.md#恢复树七项容量实测)。

本轮原件在恢复树 `artifacts/fixed-catalog-recovery/component-first-20261021T061507Z/`：`performance/report.json` SHA-256 为 `c49472bcd8e30b54e99f15c1dabd6762f0bec0a46ba1def8bb4cd16a8be6471c`。作者外独立语义及原件复核在 worker 树 `artifacts/p02-component-review/quota-runtime/combined-review.json`，SHA-256 为 `03b40a4655a52ff5e4e571f4b91f2d8d2dfe4d37a9ec0a34338d28d4c85fdbc4`，结论 PASS；实际读取核对 4516 份文件和 4509 份 canonical body。两条被更新或删除的历史 grant 仅以独立字面字段重建核对摘要/长度，不冒充已保留的历史 raw bytes。

实测为本机 PG18 可信 fixture 小组件；每次操作新建 adapter 连接，OS/PG 缓存不受控，不能作为冷缓存、产品 QPS/延迟或 PG 原生峰值内存证据。真实 P03/P04/P06 保护和 I1 接线仍缺失。此次只更新三份结果文档；新文档冻结下的完整原 base harness、Rust、独立 functional/fault 模式、提交后验收、PR/CI/main 验收及最终原件归档仍 pending，不把旧树通过或当前组件结果挪作上述证明。
