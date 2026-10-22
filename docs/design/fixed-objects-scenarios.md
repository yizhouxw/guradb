# 固定对象读取场景与验证映射

状态：**恢复树原4d范围完整INITIAL九套件通过，hook/提交后检查/PR/I1仍待完成**。完整报告 `artifacts/harness/20261021T053114Z-e7619721/report.json` SHA `0e4364576a90dc69331eca368367e25f42eed3590d3ba251572338c5f28f965b`，绑定manifest `64f1cd3aab20ce86212968193654bb3c4bb2a3e42a21dc372bb6afd9a922c765` / checkout `e8798305c8b4fd87d31296e8c42fe3b94386c1432c3ae2ec52a4e3c04af59998`，root独立核验通过。Python232项/3804行零排除、Rust3323/3323与原21行豁免、fresh真实三driver全部通过；本次随后只改三文档，不能沿用旧docSHA。全部raw路径/报告SHA见[变更计划](fixed-objects-change-plan.md)，用户入口见[固定对象](../user/fixed-objects.md)。原warning、403、首次整仓FAIL及旧局部证据原样保留，未拼绿。

| ID / 用户可观察目标 | 操作与独立成功断言 | 拒绝/故障及边界 | 验证入口 / 当前结果 |
| --- | --- | --- | --- |
| P03-VERSION 固定历史字节 | 真实Seaweed同key两次PUT，旧VersionId的16B/2MiB+17B独立原始bytes一致 | 缺旧版、返回错版、null/unversioned、未认证versioning不回退latest | unit/functional通过；非loopback/其它后端missing |
| P03-RANGE 强完整范围 | 独立whole/block表，单块/多块/短尾块逐字节一致，206/Content-Range/VersionId精确 | whole局部、非整块/越界、错误proof authority/身份/表、错SHA/短读/多读拒绝 | unit/functional/faults本机通过 |
| P03-AUTH 当前权限 | 本机内存callback记录epoch，缓存/非缓存返回前重查 | 跨binding/成员外ref、预撤权/传输后撤权、过期/错误backend凭据不给字节 | unit/functional通过；真实PG授权/暂停/取消配对missing |
| P03-CACHE 成本与结果 | 冷/热/完整超256KiB/重复完整，GET3/0/30/33，独立字节/校验/输出一致 | 版本/摘要/块表隔离、淘汰后重取、权限不能由cache绕过 | unit/performance本机通过；无产品baseline |
| P03-SCOPE 累计资源 | 同scope跨read/失败/重试，固定numeric快照分列received与server sent，wire=header+body | 每次重置、隐藏重试、预算不足分配/请求、输出双份漏计拒绝；scope并发拒绝 | unit/三driver通过；trace截断仍有真实last-close |
| P03-DEADLINE 全网络时限 | 原截止/mono锚/最后正recv/关闭/返回均落盘；首部/body停顿/滴流/缺EOF含清理502.55–507.95ms<700ms | 不足250ms准入拒绝；真实连接停顿与跨主机不外推 | unit/fault server本机通过；连接停顿认证missing |
| P03-CANCEL 取消与清理 | 本机首部/body/EOF事件取消含server清理5.90–16.04ms<100ms，active=0 | 前置/返回前取消及callback异常单元；取消不延长期限、不新attempt | unit/faults本机通过；PG网络取消missing |
| P03-HTTP 有限协议 | 明确loopback path-style请求与完整Content-Length/EOF | DNS/IPv6/TLS/非loopback/代理/重定向/压缩/TE/chunked/1xx/重复CL/超大首部/错误Range拒绝 | unit/functional/faults本机通过 |
| P03-RETRY 故障恢复 | 独立server注入429/503，3次实际GET与累计scope一致；owned socket失败单元 | 认证/校验/404不重试；耗尽稳定错误，原deadline优先 | unit/faults通过；非本机网络认证missing |
| P03-SIGN 编码与认证 | 正规SigV4；真实错误access/secret，空格/中文/%/+/重复斜线固定GET，字面%2E单元 | 实际`.`/`..`在signer/cache/I/O前unsupported，0 GET；原dot PUT403 SignatureDoesNotMatch保留，negative-only占位非真实版本；改target/过期/自动凭据拒绝 | unit/functional通过；真实临时凭据/STS missing |
| P03-LOG 日志无凭据 | 实际组合根root DEBUG与异常路径，token/secret/signature/URL canary审计通过；快照数字白名单 | 库不改全局logger；无raw header/异常/URL；Lab凭据及原container日志不纳入公共raw归档 | unit/三driver本机通过；真实STS missing |
| P03-SYNC 同步边界 | 普通无running loop线程调用；同scope多次读共享总账 | 已有loop在创建coroutine/请求前拒绝，不隐式线程/nested loop；async桥后续 | unit/三driver本机通过 |

所有输入为分发合成字节与本机Lab资源，许可/生产凭据不入库；大型对象按固定规则生成并冻结manifest摘要。报告绑定当前commit/checkout、依赖、image/config/seed与输入摘要，未跑项保持missing；synthetic与本机结果不作产品baseline。

兼容/迁移：新增模块口，不改变旧M0/M1/M2；无生产数据迁移。取消/失败清理同一owned连接，缓存可丢弃，重新读仍固定原版本。真实 PG目录、P04/P10接线、媒体代理、GC/pin执行、TLS/真实云/多机仍缺证据。完成前逐项补实际报告、成功/负例与独立review，不只链接测试文件。
