# P02 固定目录场景与验证

## C1 父控制增量（有限客户端控制已验证）

| 场景 | 必须独立核对 |
| --- | --- |
| CC1 最初锚点 | bind前已耗时后期限只缩短；wire deadline-bound=ttl；同query/view/pin/epoch。 |
| CC2 PG等待 | 100ms父控制黑洞/paused SQL/held rowlock≤150ms返回且socket关闭；同取消和更小page/cohort，PGattempt/真实wait不填0。 |
| CC3 最后边界 | authority/取消callback后fresh clock，连接/SQL/COMMIT检查；COMMIT尝试后中断只unknown，无绑定/epoch成功输出。 |
| CC4 原request清理 | 无binding且已过期/撤权found可精确released；错主体/delegation/完整request拒绝，原pin/query计数、metadata bytes/epoch不变。 |
| CC5 unknown/absence | 真实bind及cleanup COMMIT等待/响应丢失后SQL仅0或1query；同原身份清理；absent永远unconfirmed，无自动第二bind，无伪墓碑。 |
| CC6 成本与回归 | 固定32新parent/1000ms读+独立≤5s cleanup，control≤120s；真实invoice+T0，原3mode工作量/7quota/阈值/单位完整保留。 |

本次SOURCE13 `98b7032d` 下 CC1–CC6：39纯单元和control42case（含32query）、原三模式实际PASS；control SQL记录/100raw及费用边界获P01有限独审c8f3c52a。证据索引 `artifacts/c1-parent-control-source/real-first/evidence-index.json`（7ca85c56）。32query读最大25.704ms、cleanup最大11.456ms；blackhole100.262ms、paused SQL客户端100.228ms、行锁deadline95.554ms/cancel26.722ms。paused整段夹具恢复178.019ms独列；真实COMMIT generator wait已发生后返回unknown，found只精确released，absent仍unconfirmed。

CC2/CC3这里只验证客户端返回与FDclose，未确认serverbackend停止或PG cancel确认；完整server成本、PGnative memory未测。严格覆盖/完整任务/真实pair/I1未通过，不以旧组件或当前有限独审替代。原失败日志保留。

这是C1 catalog模块定义，不是PG→P03/P04共同memory/对象输出、Rust/bridge/公共客户端或I1证明；C2持久closed-request/schema迁移未做。旧86fc本地证据不能替代本次源码/新control mode结果，远端CI阻塞与禁止合main保留。

状态：恢复树运行前34文件清单下，26项针对性单元、232项Python测试/4028行零排除与真实PG七容量performance组件、独立语义和原件复核PASS。下表其余完整验证义务及新functional/fault、Rust、完整原base门禁和提交/CI/main仍pending；本次仅修订结果文档。手册：[固定目录](../user/fixed-catalog.md)，计划：[P02 首片](fixed-catalog-change-plan.md)。

| 场景 ID / 目标 | 操作和独立成功断言 | 失败/恢复断言 | 验证入口与当前证据 |
| --- | --- | --- | --- |
| FC01 身份与初始化 | 独立 schema version 1、global dataset ID 与 immutable tenant；SQL 核对旧 schema 未变 | 重复不同行 tenant/错误版本/无管理员拒绝 | unit + real PG driver；pending |
| FC02 登记发布 | 完整 T，g→g+1→g+2，登记未发布不可 bind，发布后 pointer/回执唯一 | 不同 target/旧 owner/CAS/旧 active plan 即使刷新 CAS 仍拒绝 | 独立连接/SQL 状态；pending |
| FC03 同 head 重建 | 原 revision bytes/parents 不变，新 view；旧 view 正常读取 | revision ID 内容冲突、历史 nonhead 恢复、schema 改写拒绝 | unit + real PG；pending |
| FC04 幂等与 unknown | 同 op 同 fingerprint 原 receipt；真实 effect 后故障，再 reconcile | 不同 fingerprint 不覆盖；reconcile tombstone 阻止迟到原请求 | 提交边界故障注入+独立 SQL；pending |
| FC05 对账权限 | 已有 receipt 可在当前授权下重放；管理员 absent terminalization | wire 不建立身份、reconcile-only/他人操作无权 terminalize | real PG；pending |
| FC06 原子固定读 | bind 同事务固定 view/auth/lease，新发布不漂移 | 注册未发布/无保护/未授权/跨租户/过期拒绝 | 独立 PG 连接；pending |
| FC07 bind 丢响应 | 同完整request envelope/query ID返回原binding bytes | request/trace/cancel/timeout/budget/caps或subject/delegation变化冲突；过期/已release ID不复活 | 提交边界注入+并发发布；pending |
| FC08 当前授权 | grant epoch 单调；撤销/regrant 后旧 binding 拒绝 | pin/旧 index/伪造 JSON 不能授权；owner 交接不等于撤读 | real PG + unit；pending |
| FC09 lease cleanup | 过期/撤权 owner 可释放原 exact lease，重复幂等 | 篡改 lease/owner/budget/context 不影响其他 pin | real PG；pending |
| FC10 deadline/容量 | 连接/SQL/commit/锁等待计入原admission；全部query身份和metadata字节quota原子 | 黑洞握手/暂停PG/expiry/预留g+2溢出/满quota fail closed；满额精确清理/已知重放仍可用 | 七容量performance与独立SQL已PASS，见文末；本轮新transport/fault与完整门禁pending |
| FC11 canonical 持久性 | bytea 往返非 ASCII/escaped NUL/full int8/typed NULL；restart 后 bytes/receipt 相同 | 损坏 bytes/SHA/lookup列拒绝；旧备份恢复自动检测/外部fence明确missing，人工停整个adapter是操作义务 | real PG restart/corruption；首次因动态映射变化失败；显式固定测试host port并核对重启前后，修后pending |
| FC12 管理副作用幂等 | provision/grant/revoke/rotate同op同immutable参数返回原AdminResult；effect/result同事务 | 丢响应后status absent只unknown，同op锁下重试一次；旧revoke replay不撤新grant、不同参数冲突、共享满quota已知重放可用 | private codec/unit+真实PG提交边界/独立SQL；pending |
| FC13 中断与COMMIT等待 | COMMIT前中断传播；尝试后BaseException/cleanup失败保守unknown，不覆盖未知结果 | 真实paused COMMIT在原5秒deadline内关闭，返回容差50ms单列；恢复PG后独立SQL effect/receipt对账，同intent重试至多一次；blackhole须服务stop前观测peer EOF | transport unit+真实PG driver；pending |
| FC14 验收证据与资源归属 | 首次源码身份早于生产/fixture导入；before/after一致且真实PG日志成功提取才可pass | 导入期间改源码拒绝假绑定；logs非零不绿；artifact写失败仍尝试唯一命名owned PG清理。成功adapter连接计量不冒称所有PG attempt | 独立driver生命周期负例；待实现/运行 |

共同前置：锁定 Python/Psycopg/PG18、可信 embedded principal、显式 fixture protection authority、隔离动态端口与非敏感 DSN；不是新公开客户端认证。数据为可分发合成 fixture，不代表实际源/索引保留。性能/故障使用固定 seed/规模、120秒 driver 上限和单一受控窗口；不适用产品性能 baseline。

文档先行证据计划保存于 `artifacts/fixed-catalog/docs-first.patch`；最终补实际命令/报告、checkout/数据/环境摘要、独立审查与缺口。兼容/恢复按手册：新 schema additive、旧 reader 独立、新 pin/receipt 不盲降级或删表，unknown 独立对账。所有验证未完成前保持 pending。

## FC10 行容量追加映射（源码前历史合同，结果见下节）

旧c480源码的独立raw复核b68bff78只证明512operation和8MiB边界；旧25unit/229Python/4028覆盖及PG三driver不补齐本表。新增仅接performance，不删原功能、operation、字节与transport用例，不改变120秒、100ms/5秒及单列50ms故障测量容差。

| 子场景 | 真实写入与独立SQL字面预期 | 满额与无部分效应断言 |
| --- | --- | --- |
| FC10-G | 新dataset，经公开admin写64个不同subject/delegation；grants=64、operations=65、policy_epoch=65 | 新65号拒绝且完整SQL账本不变；同op旧result重放不变；更新已有键仍64行、operation=66/epoch=66，再重放旧grant不撤回更新 |
| FC10-I | 首目标125个独立artifact+resource/revision/source/view=129身份；第二目标126个新artifact+新view后恰256；targets=2、operations=6 | 第三个目标仅复用已知artifact并增加新view，尝试257身份时原子resource_limit；无新view/target/receipt/generation或metadata，已知register/publish可重放 |
| FC10-T | 同revision/source/同artifact固定bytes，仅128个新view逐次register+publish；identities=132、targets=128、operations=258、generation=256 | 129号目标在identity/operation/字节均有余量时拒绝，无部分effect；旧receipt重放原bytes且不增加计量 |
| FC10-Q | 紧凑合法scan-only固定view逐一实际bind1024个ID，含短TTL过期、已release及最后新建live项；不改变query最大TTL | 第1025号拒绝、full-request live重放原bytes且不新增metadata；expired/released不复活；expired exact release、重复/cleanup释放不腾名额；伪造/异主lease拒绝；读grant撤销后owner仍能清理 |
| FC10-D | 所有其它场景结束后，经provision补至16个global dataset；每个有唯一tenant/provision结果 | 第17个拒绝且全局SQL账本不变、无dataset/operation孤儿；满额原provision及status返回原bytes |

每个target的canonical envelope先核小于1MiB、数组不超过128；SQL独立重算所有body/intent/receipt/request/binding字节并与metadata_bytes对照，dataset总量小于8MiB，query负载不靠缩减原512op/8MiB输入换过。各拒绝前后比较完整行/bytes/计数/epoch/generation/已知摘要，不从生产LIMITS读取expected。全部新raw由driver现有生命周期保存并绑定新源码；当前只有先行合同。

## 恢复树七项容量实测

运行绑定34文件清单 `2432c634478c7327786b5b42ff85aa89002c24855a56b3f217e74cde0d156955`；26项针对性单元、全量232项Python测试PASS，4028/4028适用执行行、missing0/excluded0。真实PG performance为31.526968秒、原120秒不变；以下全部由实际adapter写入、独立SQL及canonical账本核对，不是SQL灌入的模拟行。

| 必要容量trace / 场景 | 实际计数与成功行为 | 边界拒绝和副作用核对 |
| --- | --- | --- |
| `shared-admin-cf1-512-receipt-capacity` | 共享admin/CF1 operations恰512，原负载完整保留 | 新operation拒绝；原已知回执不重复effect或新增计量 |
| `actual-canonical-byte-capacity` | 原8MiB准入工作集接受14个view，metadata_bytes=7905933、generation=28 | 下一目标超过8MiB拒绝；没有缩减原大canonical元数据负载 |
| `actual64-grants-update-and-old-replay` / FC10-G | 满64grant；更新已有键后operations=66、policy_epoch=66 | 新65拒绝且全账本不变；已知结果重放不计费，旧grant replay不撤回新更新 |
| `actual256-identities-under-other-quotas` / FC10-I | identities=256、targets=2、operations=6、generation=4 | 尝试257仅增加新view时原子拒绝，旧register/publish回执重放不改账本 |
| `actual128-targets-with132-identities` / FC10-T | targets=128、identities=132、operations=258、generation=256 | 第129目标拒绝，身份/operation/字节仍有余量；无部分target/receipt/身份或计量 |
| `actual1024-mixed-query-identities-and-exact-cleanup` / FC10-Q | 1024次真实bind，清理前released=1、expired=1、live=1022；真实过期等待0.002736秒，计入原总时限 | 第1025拒绝；live完整request重放bytes相同、不增metadata；expired/released不复活；精确/重复/撤权后owner清理不腾query名额，伪造及异主lease拒绝 |
| `actual16-global-datasets-known-provision-replay` / FC10-D | 最后填满16个全局dataset，已知provision/status仍返回原bytes | 第17拒绝，全局SQL账本不变，无dataset/operation孤儿 |

原件：本恢复树 `artifacts/fixed-catalog-recovery/component-first-20261021T061507Z/performance/report.json`，SHA-256 `c49472bcd8e30b54e99f15c1dabd6762f0bec0a46ba1def8bb4cd16a8be6471c`。完整argv/log/exit/wall及前后源码身份、实际输入/SQL记录在同轮目录；source-before/after相同，服务日志提取和owned清理返回码均0。独立复核：worker树 `artifacts/p02-component-review/quota-runtime/combined-review.json`，SHA-256 `03b40a4655a52ff5e4e571f4b91f2d8d2dfe4d37a9ec0a34338d28d4c85fdbc4`，逐份核4516原件/4509 canonical body、十份SQL witness及语义关联，结论PASS。两条替换/删除的历史grant只由独立字面字段重建核SHA/长度，不作为保留的历史raw计数。

范围是本机PG18可信fixture的容量组件；OS/PG缓存不受控，未证明冷缓存、产品吞吐/延迟、PG原生峰值内存或真实保护/I1。旧重启FAIL595551及旧c480各模式原件保持历史结论；performance包含的共享正常场景不冒充本轮独立functional/fault模式通过。此次文档更新后的新冻结、完整原4d harness、Rust、提交后检查、最终raw归档及PR/CI/main仍pending。
