# 固定读取核心阶段的有限门禁适配

范围：ADR0027、20261029-fixed-read-core；内部工具变更，不改变数据库API。
基点 a7e49aa；独占 codex/core-gate-20261029，receipt
6f0a46d93fb54afdbfe4226656625ada。通过patch交给development整包集成，
本实例不运行重Rust/Docker，也不把toy测试当产品通过。

验收：Markdown/RST自动仅repository；核心阶段必须明确core/fixed-read，
只接受本包已知写域，运行repository/policy/contracts、有限harness自测、
变更Rust源fmt与四个受影响package的clippy/test、真实HTTP driver。
stage绑定receipt、report、完成checkpoint；源码或逻辑变化使证据失效，
失败/缺命令/缺日志不得结项；旧强化/发布门禁和历史失败保留。

风险：门禁适用时机变化，不降低原命令负例/预算。核心不做覆盖率资格、
全系统、性能/长稳或发布声明。格式只查本次Rust源，旧全树fmt失败保留；
删除源仍进入选路与checkout绑定，删除后编译验证引用。
新文件/参数、越域或混合未知改动明确拒绝，不能靠core避开系统义务。

验证：工具协议使用独立Git/toy命令证明normal hook、check、finish、
checkpoint和拒绝路径；真实Rust/HTTP由DRI唯一资源窗口及非作者复核。
恢复：保留独占dirty/日志，基点checkpoint不变，不改旧writer或旧报告。
