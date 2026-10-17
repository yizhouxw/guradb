# index：全文、ANN 与图物化

继承根 [AGENTS](../../AGENTS.md) 与 [harness](../../harness/README.md)。

重点不变量：INV-001 / INV-002 / INV-003 / INV-004 / INV-007 / INV-009。

变更验证：固定源版本/模型/分析器、稳定 ID、删除/压缩映射、Lance 派生而非双主、全文统计、图环/扇出和全局 recall；故障不能产生半发布索引。计量副本/历史/构建峰值。

先运行 plan；按受影响范围补齐功能、性能与故障验证。当前无运行实现，登记了不变量不代表已经覆盖。职责边界见本目录 README；跨边界变更同步 architecture.toml 和 ADR。
