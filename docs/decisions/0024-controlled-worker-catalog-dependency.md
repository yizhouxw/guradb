# ADR 0024：固定 FD worker 的目录依赖

状态：集成候选，须独立复核及完整本机门禁；2026-10-24。

固定 FD worker 的已实施合同要求真实 C1 ControlledReads，禁止模拟授权替代：fixed_fd_worker 对类型与原 parent checkpoint/monotonic 做校验，fixed_fd_entry 组装 FixedCatalog/TrustedPrincipal/CatalogReadControl；所有授权、pin、撤权、保护与对账仍归 catalog 唯一所有。原 architecture.toml 未声明这条新增的真实 Python 依赖，完整 policy 已实际拒绝 connectors→catalog，失败报告保留。

明确 connectors→catalog 的有向依赖，catalog→storage/common 不变，没有逆向边或环。这里只承认既有私有固定 FD 组合所需的目录消费关系，不移动目录职责，不允许复制授权/发布状态到 connector，不扩大公开入口或支持白名单。通用格式/读取适配仍按其原合同；若今后拆独立组合包，需单独迁移并验证身份/profile。

这是架构清单与实际已审合同对齐，不绕过 AST 依赖检查：未知 owner、未允许依赖、循环与动态导入继续拒绝。核验要求为完整 policy、原组件/负例、真实四场景与 strict，任何失败不算通过；该依赖不证明完整产品发布。恢复通过独立 revert 与对应代码范围处置，不仅删除边使既有代码失检。
