# query：查询与混合检索

继承根 [AGENTS](../../AGENTS.md) 与 [harness](../../harness/README.md)。

重点不变量：INV-001 / INV-008 / INV-009 / INV-010 / INV-011 / INV-012。

变更验证：PG18 差异、精确向量/小图真值、过滤前置、各路全局窗口/RRF、近似质量、冷回表和取消预算。不得把远程检索藏进逐行 UDF，不能以漏召回换提速。

先运行 plan；按受影响范围补齐功能、性能与故障验证。当前无运行实现，登记了不变量不代表已经覆盖。职责边界见本目录 README；跨边界变更同步 architecture.toml 和 ADR。
