# catalog：目录、提交与发布

继承根 [AGENTS](../../AGENTS.md) 与 [harness](../../harness/README.md)。

重点不变量：INV-001 / INV-003 / INV-004 / INV-005 / INV-006 / INV-007。

变更验证：旧任务晚完成、源提交成功但响应丢失、发布前后崩溃、目录 CAS/fencing、权限撤销和 pin。PG 小控制面不存业务逐行数据，不能承诺跨外部湖原子事务。

先运行 plan；按受影响范围补齐功能、性能与故障验证。当前 M0 实现在 crates 对应模块；覆盖范围见 docs/design/m0-validation.md，登记了不变量不代表全部覆盖。职责边界见本目录 README；跨边界变更同步 architecture.toml 和 ADR。
