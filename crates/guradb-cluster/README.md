# K124：任务信封与状态归约候选

状态：已写未发布内部库候选，未编译/验证，待 Q/G/A/T 签收；不是 IF-K wire。
本片不修改用户入口或 Python 生产路由，因此不改变用户行为。

## KQ-01 先行修订合同

Q133/6394974930指出原 `pub(crate)` 面不能被 query 跨 crate 消费。
本轮只增加未发布内部 Rust 库 facade；Rust `pub` 可调用性不是公共 wire
或稳定接口承诺。事件表、预算及父引用真值沿用下文，不改运行语义。
TaskSpec/TaskIdentity/Event 是可构造输入；TaskEnvelope 字段继续私有，
仅 validate_envelopes 可生成。TaskState 保持封装，只能从 envelope 初始化，
用 reduce 生成新状态；外部只能取得不可变借用和分轴 snapshot 副本。
不开放可写状态字段、任意状态构造器、授权、时钟、账或实际进程控制。

新树 `/Users/chad/dev/guradb-issue124-kq01`，分支 `codex/124-kq01-facade`，
base不变；receipt `3218f942e1bc458ea3e5121793dc0faa`，恢复点
`checkpoints/20261025T074132Z-before-issue124-kq01-facade-fe5eeec1`。
先核旧树六SHA与124/6394421671一致，再逐字节迁入全部六文件；旧树及
abandoned receipt `9350ca215b90403d8851ab1b273c5b81` 不动。原两unit文件
仅原样迁入；本节先于 facade 源码修订写入，记录本轮 docs-first lineage。

新增 `tests/facade.rs` 是真实外 crate 导入/消费用例源码，覆盖三片成功、
失败/unknown/cancel分轴、冲突后消费方闭锁和聚合拒绝；expected为字面值。
它不使用 `#[path]` 偷接私有生产模块，按 Cargo integration-test 机制等待
E manifest 接线后编译/执行。无 manifest/实际执行证据时保持 NOT_RUN。
本轮只编辑 README/lib/envelope/state/facade 五文件，不改原unit测试、
Cargo/root/lock/common/selector/排除或 Python；不运行格式/编译/测试。

## 先行合同与范围

任务 #124、A121-v1/6394254942、K124-stage0/6394306777。
基点 `aae4a1a4c2f69bcf5d86187bbb777da2aa6b2678`；分支
`codex/124-task-envelope-state`；receipt `9350ca215b90403d8851ab1b273c5b81`。
此文在行为源码之前写入，作为内部场景 K124-pure 与有限变更计划。

支持候选：借入已有 `cf1a/1.0` QueryContext/Budget，固定三个任务，
验证身份、payload 指纹形状、各维 child cap 和三片 checked 总和，
纯函数记录取消、期限、结果、退出、收割与未知/清理失败的独立观察。
预算比较不预约、不扣账，不签发授权，不验证真实 payload 或后台证据。
身份文本仅非空且匹配；不规定新的公共 UUID/序列化格式。

拒绝候选：错 task/attempt/query/shard/指纹、重复片、不同父引用、
超过父预算或整数溢出、冲突/迟到结果、乱序收割、失败洗成成功。
不创建父 Control、计时器、账本或重试；不执行 I/O、线程、spawn、
kill/wait/reap、网络、native 或实际恢复，不承诺 RSS/真实停止。

## 固定事件真值

| 输入事件 | 记录或拒绝 |
| --- | --- |
| Started | 未启动且未取消/过期/失败/未知才记录启动；完全重复幂等 |
| StartFailed(code) | 仅未启动可记录；不虚构 exit/reaped；冲突失败拒绝 |
| CancelRequested | 仅请求轴置位；不代表已停止；成功终态后拒绝 |
| DeadlineObserved | 仅期限轴置位；不重置 deadline；成功终态后拒绝 |
| SuccessCandidate(digest) | 已启动且无禁止成功的观察才暂存；同结果幂等、冲突拒绝 |
| FailureObserved(code) | 失败粘滞；不被成功候选覆盖；回收观察仍可补齐 |
| ExitObserved(code) | 已启动才记录；0 不代表收割；不同退出码冲突 |
| Reaped | 必须先有 exit；仅记收割观察；完全重复幂等 |
| OutcomeUnknown / CleanupFailed | 分轴粘滞；后续 exit0/reaped 不能清除 |

成功候选、exit0、reaped 均有，且无失败/取消/过期/未知/清理失败，
才是单任务“模型成功”；固定三片全满足才能聚合成功。
部分启动失败、未完成、缺片或任一未知都不得变成三片成功。
最终成功只允许完全相同的既有证据重放；其余事件拒绝。
所有拒绝返回错误、输入快照不变。消费者必须处理错误，不能丢弃冲突
再把旧成功快照当作有效新结果。无生产消费者接线，本片不证明实际停止。

## 验证、风险与交接

独立字面事件真值在 `tests/unit/envelope.rs`、`tests/unit/state.rs`，
由 `src/lib.rs` cfg(test)/path 接线；expected 不由归约器生成。
覆盖预算每维/总和/溢出、错身份、乱序、重复/冲突、迟到结果、
取消与结果顺序、unknown/cleanup 粘滞和部分启动；真实进程 oracle 后置。

初始K0六文件范围：本 README、src/lib.rs、src/envelope.rs、src/state.rs、
tests/unit/envelope.rs、tests/unit/state.rs。源文件各不超过 600 行。
本片不涉及持久布局、数据迁移或外部副作用；原 Python 权威不退出。
恢复点为 task-start checkpoint；停止用 task-abandon 保留 WIP。

Cargo.toml、根 workspace/lock、selector/排除绑定归 E；生产依赖仅现有
guradb-common，不新增第三方。当前 cluster registry pending，完整 owner
包括原 Python。plan 不等于门禁，缺 Cargo 接线不能绕成独立 workspace。
编译/测试/coverage/module/pair/system/release 均未运行；Python80%、
Rust适用100%、原排除不扩、独审和精确 main 证据仍须后续真实窗口完成。
性能/进程故障/恢复证据未测，不以纯模型声称这些义务通过。

初始K0实际执行 task-start、拟议两源 plan 和完整六文件 plan；plan 均成功
返回选择结果，cluster pending 使 minimum_level=system，影响 cluster/query/
gateway。这不是质量门禁 PASS。PATH 及常用本机安装位置未找到 rustfmt，
未安装工具/启动容器补跑；格式与 clippy/编译保持未验。当时入口均私有，
现按KQ-01仅经重导出供跨crate消费，尚无生产接线；没有allow/expect豁免。
E 的 Cargo 接线及 Q 消费/接口签收必须使真实构建与正常门禁成立后再提交。

KQ-01 本轮实际 plan 已返回七文件范围（五修订候选加两原样unit）；
minimum_level仍为system，原因为cluster profile pending；无质量套件执行。
本轮未执行rustfmt/编译/测试，不以源码存在宣称外部用例可编译或通过。

## K-FACADE-PREP-v2：独立单target准备（未执行）

Refs #124 PM6407895796、A157/6407136646。新树/receipt
041859d470164e4e80ab5651cafb7cd5，base d83d253cd9e19b3bf0976fc11217660d1ee9eede。
本节先于controller写入；不改用户入口、K模型或三facade/两unit。
原K七件逐身份迁入，Cargo.toml是E132原bytes；root/member/lock/common/schema仍E域。
私有artifact为controller.py/tool-arguments.json/source-inputs.json/source-paths.txt/
handoff.json/negative-cases.md，仅完整代码候选，不是可执行封套或签收。
list rc0后先验完整三名多重集才准run；无筛名、无sort-u消重。
source资格和window授权均False，未绑定name/nonce/RUN/时间；执行入口在fork之前拒绝。
复用173父监督/有限日志/真实wait/持久发布，主900+cleanup60/总960仅未来请求，
解释器前UNKNOWN、旧132/P/117真实拒绝不被本准备解除。
本轮只静态AST/shlex/身份/diff与plan，不调用controller/负例/Cargo/格式/测试/容器。
T/E后续签实际版本，A核新增边界；缺共享接线保HOLD，不伪完整闭包。

## 2026-10-28 integration observation

The earlier NOT_RUN entries above describe the candidate at the time they were
written. The integrated source was later compiled offline with the fixed Rust
image, and the 11 library and 3 external facade tests passed. This does not
validate production runtime, process ownership, authorization, or resource
accounting; those remain separate obligations.
