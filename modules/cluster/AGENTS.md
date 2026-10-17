# cluster：分布式与资源隔离

继承根 [AGENTS](../../AGENTS.md) 与 [harness](../../harness/README.md)。

重点不变量：INV-004 / INV-005 / INV-006 / INV-008 / INV-009 / INV-011。

变更验证：真实多 worker 与全局归并、重复 task、过期 worker、协调器重启、shuffle/spill/背压/取消、训练/构建干扰。单机线程/分区并行不能替代分布式证据。

先运行 plan；按受影响范围补齐功能、性能与故障验证。当前无运行实现，登记了不变量不代表已经覆盖。职责边界见本目录 README；跨边界变更同步 architecture.toml 和 ADR。
