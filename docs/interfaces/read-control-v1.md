# R1 Read-Control v1：内部目录受控读合同

版本：`read-control/1.0.0-rc1`。状态：IF-R0 作者候选，待 #46 独审、#47/#48/#49 逐方法签收、产品必要复核与 PM 登记冻结；不是已实现 API、后端通过或实施授权。

规范摘要：`6cfb1886bd537dba7c38f42838f01532898e24d0f133469ac2d0462a580c18b4`。计算范围为下方 BEGIN/END 标记行之间的原始 UTF-8/LF 字节，不含两行标记及本段；不归一化空白。签收同时绑定版本、摘要、PR 完整 H 和方法 ID。语义修改升级 rc 并重签，H 变化按受影响范围重新复核；单一作者或独审通过不等于冻结。

本任务仅写本文与[模块合同](../design/module-delivery-contracts.md)，无数据库用户行为变化。既有 [A schema](../../api/cf1a/schema.json)、[类型](../../crates/guradb-common/src/cf1a/types.rs)和[同步 ports](../../crates/guradb-common/src/cf1a/ports.rs)保持原义；本文不修改其编码或假称旧签名已提供父控制。

<!-- BEGIN READ-CONTROL-V1 -->
## 1. 版本、出口和责任

规范版本为 `read-control/1.0.0-rc1`，profile 为 `r1-local-service`；未知版本/profile 在任何 PG I/O 前以 `unsupported_version` 拒绝，不协商降级。

唯一出口是：真实 Rust query 消费真实 Rust catalog/PG 签发的 binding，构造固定 schema/view 的内部计划、调用唯一 Compiler 并显式结束/交权。无源扫描、SQL 数据行结果、HTTP/PG 新用户入口或索引承诺，不称 I1。

| owner | 方法/值责任与直接消费者 | 允许依赖及禁止项 |
| --- | --- | --- |
| common / 架构 | 本文数据类型、校验与受控 catalog trait；C/Q/G 消费各自必需子集 | 不依赖上层，不连接 PG、不持有 SQL/DataFusion 计划或运行时托管状态 |
| catalog / C（#47） | RC-B/RC-A/RC-F/RC-R；Q 为直接调用者，具名托管宿主消费 cleanup 结果 | common/storage；唯一授权、view、lease、托管和 PG 状态权威 |
| query / Q（#48） | RQ-1/RQ-2 与请求/执行指纹、单父 ledger；消费 C，交后续 G | 现有 query 允许边；不另造 PG 目录、授权或 SQL parser |
| gateway / G（#49） | HI-1 受控宿主身份配置映射；给 C/Q 提供身份输入 | 现有 gateway 允许边；R1 不拥有另一套 query 终态或公开句柄服务 |

R1 不使用 storage/connectors/index/cluster 的新增端口，不要求它们先签未来合同。当前 ADR0024 的私有 Python connectors→catalog 边保持；本文不修改机器 DAG。

## 2. 基础类型和不可变身份

下列为后续实现必须遵守的 Rust 语义类型名；不是本文已经编译的声明。`Id` 沿 A 的 id 校验，`Sha256` 为 32 字节、展示时小写 64 位 hex；数值不经浮点转换。原 A `Contract`/`Cell`/`Budget` 不复制为另一套 wire 类型。

| 类型 | 必需字段/约束 |
| --- | --- |
| `HostPrincipal` | `issuer_id: Id, config_sha256: Sha256, tenant_id: Id, subject_id: Id, delegation_ref: Id`；不含 bearer/PG 密码或客户端指定的 admin/cleanup 布尔值 |
| `R1QueryRequest` | 完整原 A `bind_request: Contract`、`sql: String`（原 UTF-8，不改写后取摘要）、`params: Vec<Cell>`；只准备当前受限 SQL，不执行行读取 |
| `ReadRequestKey` | tenant/dataset/query/request 四个 A ID、principal 三元组、`issuer_id/config_sha256`、`bind_sha256`、`execution_sha256`；全生命周期不可变 |
| `ExactLease` | `pin_id, lease_id, read_view_id, data_revision_id, binding_sha256`；连同完整 key 校验，不只凭 query ID 或 pin ID 释放 |
| `BoundRead` | 原 A `read_binding: Contract`、原 key；lease 从 binding 提取并交叉校验，不另生成 |
| `CustodyTicket` | 原 key、`record_version: u64`、`state: CustodyState`；只引用同一 PG 权威，不是访问授权或允许读数据的句柄 |

`execution_sha256 = SHA256(cf1a::canonical({profile, principal, bind_request, sql, params}))`：`principal` 是 HostPrincipal 全部五字段，`bind_request` 是完整 A envelope，`params` 使用 A tagged Cell，`profile` 为上述固定字符串。禁止仅对 SQL、A request payload 子集或格式化 SQL 取摘要；同 query ID 的任一字段变化为 `conflict`。

HI-1：`resolve_host(config: &VerifiedHostConfig, alias: &Id) -> Result<HostPrincipal, ContractFailure>`，由 G/可信组合根实现，不属于 IF-R1 common 的认证实现。配置来自运维预装的只读配置，拥有者和读取权限受部署保护；alias 仅在该配置内选择，普通请求不能提交配置文件、issuer、保护 target 或角色。C 的 session 绑定配置中一个 principal，并将输入与该配置及 PG 当前 grant 一致性复核；摘要只作身份绑定和审计，不凭摘要本身建立信任。

每个可信配置entry必须列 `alias: Id, principal: HostPrincipal, dataset_ids: Vec<Id>, permissions: Set<ReadR1|CleanupOwned|CustodyReconcile>`。这些权限来自宿主配置而非HostPrincipal/A wire，C必须拿到同一可信配置并复核：ReadR1仍需PG read grant；CleanupOwned只作用原owner/key；CustodyReconcile只作用同PG记录已指派给该宿主的key。未知权限拒绝，任何cleanup权限都不能签发新binding或返回受保护数据。

上述entry为解析后的视图。配置canonical原文只含 `config_version, issuer_id, entries[{alias,tenant_id,subject_id,delegation_ref,dataset_ids,permissions}]`，不含派生principal或自身摘要；`config_sha256`为该完整原文的SHA256，随后注入HostPrincipal，避免摘要自引用。alias和principal三元组均唯一，冲突配置在请求准入前拒绝；摘要进入execution canonical时使用小写hex字符串。

本 profile 仅一个执行读取的受控宿主 service 身份，可另配具名维护托管身份；不支持任意多用户查询委派、跨宿主 mono、OIDC 或公网认证。首片目标由运维显式预装固定 target allowlist，并检查登记的保护到期；回执固定记录 `protection_level=FixtureOnly`，只认证该内部配对前提，不证明真实源对象存在、生产保留保护或索引完整。测试不能自称生产认证。未有配置匹配、grant 或有效 target 保护则失败关闭，不取 latest 补默认值。

## 3. 单父 Control、单位和准入

`ReadControl` 由可信 Q 宿主在请求解码/排队/bind 前创建并拥有，不可从 A 或客户端反序列化；子调用借用同一实例，不得复制重置。

| 字段/操作 | 必需语义 |
| --- | --- |
| `version, owner_id, control_id, key` | 绑定规范版本、唯一宿主 owner 与完整请求 key；原 key 建立前，宿主先持有接收/解码额度 |
| `t0_ns, deadline_ns: u64` | 同宿主同一 monotonic 时钟域的纳秒；构造时 checked 加减/乘法，回退/溢出/非法时钟在 I/O 前拒绝 |
| `cancel: CancelHandle` | 仅内存检查、无 I/O；状态只从 false→true，不清除、不代替后台停止证明 |
| `required_guarantees: GuaranteeSet` | v1仅支持`HostLogicalQuota`与`ExplicitUnknown`；要求`PgNativeHardBound`或`ProductionSourceProtection`则I/O前unsupported，不静默接受后忽略 |
| `budget: Budget, ledger: ReadLedger` | 原九个 A Budget 字段和同父累计账；cap 取父剩余更小者，不将组件 cap 相加 |
| `checkpoint() -> Result<Remaining, ReadFailure>` | 回调后重新读 mono/wall 与取消；有效截止只收紧，子操作/PG 回调不得创造新 T0 |
| `Remaining` | `remaining_ns` 与当前预算剩余快照；不是新预算授权，provider 不能凭旧快照继续输出 |

R1 read 总时限不大于当前 query 宿主 10,000 ms 与 A request timeout 的较小值；A 原 ≤30,000 ms 校验不变。绑定后再与 A deadline、pin/grant/保护到期取更早值，过期不能因 retry 延长。所有 ns→ms 的等待值向下取整，余量不足 1 ms 则 deadline 拒绝；不能向上取整后越过原截止。

当前调用只消费已有 A 合法资源描述符及 ≤64 KiB 的 SQL+params canonical 输入；仍受父 memory/output cap 和 A envelope 上限。R1 没有 object I/O，故该维度可观测为零，但 PG 流量/内存不能归成零 object 成本；请求要求 native/PG 总硬内存保证时，本 profile 在 PG I/O 前拒绝 `unsupported`。它仅约束宿主逻辑预约，**不认证 PG/native RSS 硬界**。

`CleanupControl` 与 read control 不同：`version, owner_id, original_key, cleanup_attempt_id, started_ns, deadline_ns, budget`；每次显式调用最多 5,000 ms，配置额度不能超过托管宿主维护额度，且一次调用不暗重试 COMMIT。取消 read 不取消精确清理权限，cleanup 不恢复读权、不续读期限。新 reconcile 必须由具名托管者显式发起、另计维护费用；无无限自动重试服务。

每 key 最多一个在途受控调用；并发 bind/reauth/finish/reconcile 拒绝 `resource_limit`。是否改成 async/poll 是后端实现选择，但返回时限、不可丢尾账、fresh checkpoint 和停止证明义务不得改变；丢 Future 或关闭客户端连接不是完成。

## 4. 成功与 Err 都必须返回的证据

`ReadCall<T> { result: Result<T, ReadFailure>, receipt: CallReceipt }`。所有受控方法都返回此结构；构造/格式校验在外部 I/O 前失败时同样由宿主记录未发起 I/O，不伪造零内存/零耗时。`ReadPhase`闭集为`Validate/Reserve/Connect/Authorize/BindCommit/Prepare/Reauthorize/ReleaseCommit/Reconcile/Return`；方法ID为`RC-B/RC-A/RC-F/RC-R/RQ-1/RQ-2`，ID字段沿A的Id规则，其他计数/时间均为u64。

| 类型 | 必需字段/枚举和计费规则 |
| --- | --- |
| `ReadFailure` | `code: ErrorCode, trigger_code: Option<ErrorCode>, phase: ReadPhase, diagnostic_id: Id`；消息不含凭证/SQL参数/PG DSN。发生效果未知时 code=`outcome_unknown`，原 cancelled/deadline/backend 原因放 trigger |
| `CallReceipt` | `key, attempt_id, method_id, phase, observed_ns, request_state, usage, stop, cleanup, custody: Option<CustodyTicket>, protection_level: FixtureOnly`；不能由 gateway 根据 HTTP 成功补造 |
| `UsageEvidence` | `sequence: u64, delta, cumulative, unknown_dimensions, retained_reservations`；同 key/attempt/sequence 重放不重复入账，计数非负 checked 累加 |
| `KnownUsage` | `pg_connect_attempts, pg_sql_attempts, pg_commit_attempts: u64`；`object_requests/object_bytes/output_bytes/host_logical_live_bytes/host_logical_peak_bytes: u64`；`elapsed_ns: u64`。host memory 为 live/peak，不按批次求和；PG/native 内存及未观测 wire 字节留在 unknown_dimensions |
| `StopEvidence` | `local_io: NotStarted/Active/Stopped/Unconfirmed`；`pg_attempt: NotStarted/Active/StoppedConfirmed/Unconfirmed`；后者附 server session 身份和可信 proof_ref，无证据不得构造 confirmed |
| `CleanupState` | `NotRequired/Bound(ExactLease)/ReleasedConfirmed(ExactLease)/NotBoundConfirmed/CleanupUnconfirmed`；和 read 结果/stop 分轴 |
| `RequestState` | `NotAttempted/InFlight/Settled/OutcomeUnknown`；Settled 仅表示 bind/reauth 的已知结果，不等于查询成功、lease已释放或所有backend已停 |

attempt 先登记再发送；socket/SQL/COMMIT实际发送不得因 Err 清零。parent elapsed 为 `now-T0`，不是嵌套 PG 阶段秒数的和。成功 A Usage 只是原值接口的 delta，不能与本父 ledger 再加一次。保留预约是安全上界，不能冒称已测费用；证据缺失时标 unknown，并保留相应预约，不提前退款。

PG `StoppedConfirmed` 针对原 attempt 不再产生效果，不要求 PostgreSQL 服务进程退出；必须有该 session/transaction 的完成或服务器侧终止证据、宿主无排队续发工作的证据。PID 单独不足，须含 backend_start/会话身份避免复用。客户端 cancel 发送/返回、TCP 关闭、一次 pg_stat_activity 缺行各自不能单独证明全部终止；独立验收核 driver 与服务器观测组合。

## 5. 必需方法与顺序

以下签名约定 `ControlledCatalogRead` 实例由 C 在可信组合根绑定一个 HostPrincipal及上述可信配置。RC-B/A的key与实例身份不符拒绝；RC-F/R只允许原owner或满足CustodyReconcile且在持久记录中被指派的宿主，保留原key不改为托管者身份。common 只声明 trait/值，不实现 session、PG 或 ledger 后端。

```rust
trait ControlledCatalogRead {
    fn bind(&mut self, input: &BindInput,
            read: &mut ReadControl) -> ReadCall<BoundRead>; // RC-B
    fn reauthorize(&mut self, bound: &BoundRead,
                   read: &mut ReadControl) -> ReadCall<AuthEpoch>; // RC-A
    fn finish(&mut self, key: &ReadRequestKey, lease: Option<&ExactLease>,
              cleanup: &mut CleanupControl) -> ReadCall<ReadResolution>; // RC-F
    fn reconcile_read(&mut self, key: &ReadRequestKey,
                      cleanup: &mut CleanupControl) -> ReadCall<ReadResolution>; // RC-R
}
```

`BindInput { principal: HostPrincipal, request: R1QueryRequest, key: ReadRequestKey }`；`AuthEpoch { policy_epoch: u64, checked_unix_ms: u64, binding_sha256 }`。`ReadResolution { key, custody: CustodyTicket, cleanup: CleanupState, stop: StopEvidence }`；unknown 是合法未收敛结果，不是成功清理的别名。

| ID | 输入→结果与必要边界 |
| --- | --- |
| RC-B | 验完整 A bind request/principal/key→先持久预约/托管再发原 bind→同事务授权、固定已发布或显式指定 view、精确 pin/lease→返回原 canonical binding。Q交叉核 schema/view/key。重放同 request 全指纹只返回同一未释放 binding、不续TTL/不生新lease；冲突拒绝，已释放拒绝 expired_context，隔离中的 key 只可 reconcile |
| RC-A | 只接受 RC-B签发的完整绑定及原 key→当前 grant/policy epoch/lease/保护复核→AuthEpoch。回调后fresh clocks/cancel再允许受保护输出；撤权后重新授予旧epoch不恢复旧绑定，不能缓存epoch作为长期许可 |
| RC-F | Q宣告不再使用原请求，校验完整key与可选精确lease→停止后续read输出→独立cleanup事务释放原lease或查原request。无lease时也不能省key/request摘要；重复精确释放幂等，旧lease/伪身份不得释放新lease。撤销read grant不取消原owner的精确cleanup权限 |
| RC-R | 仅可信托管者或原owner，针对已登记原key查原request/attempt与binding/lease，必要时精确释放→返回分轴结果和持久ticket。不得调 mutation reconcile、换request ID、重试bind、选择latest或扩大权限 |

Q 的真实消费方法位于 query，不下沉 common：

```rust
fn admit_read(request: R1QueryRequest, principal: &HostPrincipal,
              catalog: &mut dyn ControlledCatalogRead,
              control: &mut ReadControl) -> ReadCall<AdmittedReadPlan>; // RQ-1
fn finish_read(plan_or_key: ReadOwnerRef,
               catalog: &mut dyn ControlledCatalogRead,
               cleanup: &mut CleanupControl) -> ReadCall<ReadResolution>; // RQ-2
```

RQ-1 用原 bind 结果的 ResourceDescriptor 构造 schema adapter，调用现有唯一 Compiler 进行受限投影/参数/类型准备，输出 query 私有 `AdmittedReadPlan { key, bound, prepared, schema_sha256 }`。它不能伪造 M0 Source/manifest 来冒充真实绑定，也不调用测试 PairQuery/stub 替代生产接缝。prepare 失败仍必须保留已发生的绑定费用/lease并进入RQ-2；plan不是执行许可，任何后续受保护使用仍需RC-A及fresh checkpoint。

顺序：HI-1/宿主预装身份→建单父Control及完整key→RC-B→核binding/schema→唯一Compiler→RC-A→返回内部准备结果→RQ-2/RC-F；取消/错误不能跳过finish或unknown交权。R1可只准备、不读一行；RQ-2既可消费成功plan，也可消费失败返回中原key，不能依赖成功拿到plan才能清理。

## 6. unknown的持久托管与迟到效果

选择**保守unknown+隔离托管**，不承诺 durable close/fence。当前 Python C1 absent cleanup 是 cleanup_unconfirmed；下面是 M-C 必须新增的持久合同，不是当前库已经支持。

### 6.1 最小持久记录与容量

C 在同一 PG 控制面增加私有 `read-control/1` 记录，逻辑唯一键为 `(dataset_id, query_id)`，同时核tenant/request/principal全指纹。记录至少保存：原A request字节/摘要、execution摘要、principal配置身份、owner/control ID、record_version、已知binding/lease、原attempt集合/服务器会话身份/发送及结果阶段、可能引用view、费用已知性/预约、托管状态、下一具名处置owner和最后回执。不是第二个发布/授权目录。

每个新Rust请求在发送bind前必须确认该记录及可能引用目标的保护/额度预约已持久化；预约事务响应未知就**不得发送bind**，返回 custody unconfirmed，后续只对账。原request/目标/费用快照不得因托管更新被覆盖；状态更新使用record_version CAS。已知binding后只引用原lease，不创建替代lease。PG迁移SQL由后续 C 任务单独实现/审查，IF-R1不含它。

R1沿用目录原每dataset至多1024个query身份与8MiB metadata预算，不新增一份独立1024/8MiB池：旧queries与新托管记录按相同key的并集计身份，实际新增/重复保留的字节全部计入原metadata，不能只计摘要。满额或不能持久保护时在bind前拒绝resource_limit；不自动删除未知记录腾位。不删除/重编号旧queries/lease，不自动解释旧行具有新托管证明。

托管状态为 `Reserved → Active → ReconcilePending → Closed`；KnownBound是Active/待清理记录的证据，不是另一套授权。Closed只有本节的终态证明允许；v1不给Closed写原子“阻止迟到bind”的含义。隔离中的同逻辑request禁止新ID重开、隐式Python/latest回退；保留它可能引用的view和预约，阻止相应GC。无关请求按原限额处理，不全库停服。

### 6.2 收敛和不收敛

- 取消只是置位/停止后续受保护输出；COMMIT发送后丢结果、backend停止未证、cleanup丢响应、一次absent均保持OutcomeUnknown/CleanupUnconfirmed。不能向用户或宿主报告cancel-complete/全部pin释放。
- found：核原request/principal/execution摘要与精确lease，幂等释放；只读grant已撤不阻止原owner或受控cleanup宿主释放原lease。
- absent：不构成终态。只有原全部bind attempts都已证实不再产生效果、无待发送续作，且独立状态证明从未绑定，才可NotBoundConfirmed；不能仅凭超时/连接关闭/TTL过期推断。
- found且原attempt已settled、精确lease释放被确认，可Closed/ReleasedConfirmed。释放确认缺失、源attempt仍可能晚到或托管持久化未确认就不Closed。独立cleanup不延长read期限。
- 宿主重启后按原key恢复托管，拒绝原read重新执行；mono值不跨重启复活。新维护Control只用于有界对账/释放，不能续读、自动重绑或退还未知预约。
- 无法取得停止/持久化证明时继续ReconcilePending，指定运维owner；v1不建无限重试调度器。一次RC-R最多一个显式有界操作，不隐藏重复COMMIT。

旧binary/reader若不能识别新托管保护，不得在有活动/未知记录时回退接管；升级/回退检查需同时核PG托管、旧lease/引用及未决操作，不能用代码revert代替数据处置。v1不能安全读取的旧未知请求必须保持隔离并交运维，不把缺字段补0/补Closed。

## 7. 错误、后果与独立验收映射

| code | 条件／后果 |
| --- | --- |
| invalid_contract / unsupported_version | 值、单位、摘要、时钟、未知必需profile/能力不符；I/O前拒绝；不得降级A或补默认 |
| unauthorized / revoked / expired_context | 宿主映射/跨主体、当前授权/保护撤回、epoch/TTL/已释放绑定不符；停止输出，保原lease cleanup责任 |
| conflict | 同key不同完整请求、binding/lease/托管CAS冲突；不覆盖/换ID重试 |
| resource_limit / deadline / cancelled | 准入、原父/清理预算或取消触发；记录实际phase/账和停止状态，不等于无副作用 |
| backend_unavailable / execution_failed / unsupported / invalid_parameter | PG不可用、query准备错误或profile不支持硬native等能力；保留原Compiler拒绝/参数错误，已发生费用/lease仍随回执保留 |
| outcome_unknown | 可能已经发生bind/释放或托管交权未知；trigger保原原因，只reconcile原key，不盲重试bind |

当效果未知时使用outcome_unknown优先，不能用cancelled/deadline掩盖。相反，已证无任何bind尝试的取消可返回cancelled+NotAttempted/NotRequired；既有lease已知时也不必伪称bind未知，但cleanup/stop依其真实证据分轴返回。

以下是未来 IF-R1/M-C/M-Q1/P-R1 的验收义务，本次documentation检查不执行它们。T独立维护字面canonical/直接PG SQL与服务端观测，不能以被迁生产编码/自身replay生成唯一期望。

| ID | 独立预期与负例 | 所属出口 |
| --- | --- | --- |
| V01 | 旧A golden/rejections字节不变；未知版本、非规范int8/NULL/ID、错完整摘要失败；修改SQL/params/budget/主体即conflict | IF-R1类型/兼容；G/C/Q签收 |
| V02 | 可信配置身份与PG grant一致；伪alias/issuer/config、客户端admin/cleanup、跨租户/委派拒绝 | HI-1/RC-B；G/C |
| V03 | bind前T0、callback后freshclock/cancel、ns→ms向下取整、时钟回退/溢出/迟到/并发拒绝；重复回执不重加费用 | IF-R1/RC-B/A与Q ledger |
| V04 | 真实PG原子bind/pin；同请求同binding/lease，改字段冲突、释放后不重绑；Q真实schema/Compiler使用同view，发布V2旧计划仍V1 | M-C/M-Q1/P-R1 |
| V05 | 撤权/重授旧epoch、过期/假binding、旧lease释放新lease均拒绝；撤权后原精确cleanup仍可执行 | RC-A/F |
| V06 | PG握手/锁等待/晚回调/COMMIT响应丢失；独立观察PG原session/attempt，不能仅看客户端返回；费用未知不填0 | RC-B/A/F，T真实PG故障oracle |
| V07 | 暂停原bind→调用方取消/丢响应→独立SQL暂见absent→放行晚提交；应持续unknown/隔离，再按原lease对账释放；重复cleanup不得动新lease | RC-F/R迟到oracle，不能预期不存在晚提交 |
| V08 | 托管预约响应丢失不得发bind；容量满/metadata超额、宿主重启、CAS冲突、cleanup丢响应与proof缺失保持未收敛，原key/引用/预约可追溯 | M-C持久兼容/托管 |
| V09 | Q Compiler准备错误/取消时仍可从失败回执的key finish；无Source/worker/stub依赖；结果不得变成公开行查询/永久授权 | M-Q1真实消费与P-R1 |
| V10 | 旧ID/lease/未决请求兼容、未知记录禁止不兼容回退；不通过只删Python源码或缩分母验收退出 | M-C/Q1精确main与停旧证据 |

## 8. IF-R1精确清单、消费者签收与后续边界

IF-R1唯一作者由PM派发；只实现common值/校验/trait，不实现任何PG、身份提供者、SQL、后台托管或用户入口。拟定精确文件清单：

| 文件 | 必须交付 |
| --- | --- |
| `crates/guradb-common/src/cf1a/read_control.rs`（新） | 本文key/principal/control、receipt/error/usage/stop/cleanup/lease/ticket值及验证；构造、比较和单位checked规则 |
| `crates/guradb-common/src/cf1a/controlled_ports.rs`（新） | RC-B/A/F/R trait与必需输入输出类型；无catalog实现导入 |
| `crates/guradb-common/src/cf1a/mod.rs` | 导出上述私有profile；旧VERSION/CAPABILITIES/A decode与ports原义保持 |
| `crates/guradb-common/tests/unit/read_control.rs`（新） | V01/V03的独立固定值、摘要/单位/溢出/账本重放与未知不抹零负例 |
| `crates/guradb-common/tests/unit/controlled_ports.rs`（新） | 受控接口的compile/use形状、Err可携原key/账、lease精确匹配及unknown非终态；fake明确不认证PG/停止 |

若实现需要动旧A schema/golden/编码/公共旧port语义，IF-R1在越域前停止，列具体必要变化并重新签收，不能暗改。新增文件遵守600行上限和common无上层依赖；完整owner分母与适用真实门禁不缩，接口存在不证明后端ready。

M-C另交同一PG托管记录/升级与容量及RC实现；M-Q1另交真实admission/schema/唯一Compiler接缝，Q内部计划类型不进common；G另交受控宿主身份映射。IF-R1不是这些运行时代码的授权。

| 签收出口 | 按同一PR H、规范版本/摘要必须逐项回应 |
| --- | --- |
| #46 T | V01–V10可独立验、方法/状态无矛盾、实现清单不偷改A；合同评审不报后端PASS |
| #47 C | RC-B/A/F/R、HostPrincipal复核、持久托管/配额/旧lease与PG停止证据可实现边界 |
| #48 Q | RQ-1/2、唯一Compiler/schema消费、父ledger/Err与失败后finish；不要求Q2 Source/F/K |
| #49 G | HI-1可信配置/service身份与拒绝、R1内部口径；不代签R2认证/句柄 |

全部必要签收/发现处置及产品词义复核齐后，由PM登记冻结版本；#51消费实际B/H和证据串行合入。作者PR、documentation suite通过、目录存在或任一单独review均不等于冻结。冻结并合入合同及所需common类型之后，才由PM另派后端任务。

后续依赖明确隔离：IF-H0负责R2主体/公开句柄、分页/状态/取消及重启恢复或拒绝；IF-A0负责旧A wire↔Arrow/lineage的所有权/兼容；IF-X负责两来源full11总≤100的artifact/统计/locator和发布，130 scan另验；训练/multihost/GC/完整恢复另片。它们不反向成为R1前置，也不在本文标冻结。

逐能力退出：M-C/Q1真实配对、兼容、费用/停止或明确unknown、独审与精确main证据齐后，才停对应Python目录读生产路径；register/publish/Jobs/训练pin/managed/其它route仍未迁，不能连带退役。Python独立oracle/SDK/AI外围保留，旧P05 HOLD不因本文清账。
<!-- END READ-CONTROL-V1 -->
