# storage：对象访问、缓存与生命周期

继承根 [AGENTS](../../AGENTS.md) 与 [harness](../../harness/README.md)。

重点不变量：INV-002 / INV-006 / INV-008 / INV-010 / INV-011。

变更验证：固定对象/校验、范围/合并读取、冷热与过量缓存；请求/字节/读放大/RSS；限流/对象丢失、取消和 GC/pin。不得让 LIST 或 rename 代替提交协议。

先运行 plan；按受影响范围补齐功能、性能与故障验证。当前无运行实现，登记了不变量不代表已经覆盖。职责边界见本目录 README；跨边界变更同步 architecture.toml 和 ADR。
