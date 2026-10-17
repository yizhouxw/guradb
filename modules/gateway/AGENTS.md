# gateway：入口、身份与生命周期

继承根 [AGENTS](../../AGENTS.md) 与 [harness](../../harness/README.md)。

重点不变量：INV-003 / INV-007 / INV-008 / INV-012。

变更验证：参数绑定、写 CTE/副作用/只读绕过、租户身份、游标/句柄授权、结构化错误、取消竞态、提交与 search_ready 分离。拒绝未支持事务/约束，不能仅看 SELECT 首词。

先运行 plan；按受影响范围补齐功能、性能与故障验证。当前无运行实现，登记了不变量不代表已经覆盖。职责边界见本目录 README；跨边界变更同步 architecture.toml 和 ADR。
