# connectors：格式与外部源

继承根 [AGENTS](../../AGENTS.md) 与 [harness](../../harness/README.md)。

重点不变量：INV-001 / INV-002 / INV-005 / INV-010 / INV-011。

变更验证：固定 snapshot、position/equality delete、field ID/schema、源过期、稳定映射与独立 reader/writer 互操作；读/导入/导出/写回分开，不能按 Java 能力推断 Rust 支持。

先运行 plan；按受影响范围补齐功能、性能与故障验证。当前 M0 实现在 crates 对应模块；覆盖范围见 docs/design/m0-validation.md，登记了不变量不代表全部覆盖。职责边界见本目录 README；跨边界变更同步 architecture.toml 和 ADR。
