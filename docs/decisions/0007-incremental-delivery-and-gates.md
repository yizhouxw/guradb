# ADR 0007：按可验收切片实施与分层门禁

- 状态：本次复审采用的实施基线；能力仍待实现验证
- 日期：2026-10-17
- 关联：[路线图](../roadmap.md)、[数据合同](../product/data-contracts.md)、[复审记录](../reviews/2026-10-17-implementation-readiness.md)
- 修正：[ADR 0003](0003-storage-and-execution-baseline.md) 的组件接入顺序、[ADR 0005](0005-agent-harness-and-quality-gates.md) 的首次运行时门禁粒度；保留其选型方向与发布质量要求

## 问题

原 P0 与共同前置 POC 同时覆盖全检索、全格式、同步、多节点和恢复，之后再建设最小产品，无法给第一条可运行链路划出有限边界。普通源码门禁又要求完整混合负载及分布式 fault registry，首个组件即被尚未实现的整库能力阻塞。

## 决定

1. [路线图](../roadmap.md) 是交付范围的唯一来源。M0 为固定 manifest/Parquet 与只读 HTTP 精确扫描；M1 为一个 Iceberg 受限源的 Snapshot 检索/训练 alpha；M2 逐片接入 ANN、受限 Graph、append-only 触发增量和单表托管 append；M3 验证真实分布式 P0；M4 满足生产发布要求。长期格式/模态目标保持，但不成为首个 alpha 的共同前提。
2. POC 就近验证并产出可复用切片。Arrow/DataFusion、Iceberg reader、Tantivy、Lance、Graph/分布式各在首次使用前验证依赖和替代边界，不要求全部联编通过才允许开始 M0。
3. 查询入口先只读；同步/导入/构建是持久作业，后续独立冻结输入上下文、operation ID、对账和权限。首次托管写限定单表受控串行 append，多表业务原子性不从发布 CAS 自动推导。
4. 在连接器/索引实现前冻结[身份、版本和保留合同](../product/data-contracts.md)。默认读已发布固定视图；无键源允许快照内身份，不能隐式获得跨版本身份/增量能力。
5. 普通内核变更必需真实功能测试、适用的语言检查、`performance-smoke` 与 `stability-component`。它们验证当前切片，并记录未覆盖项；planned/missing 仍失败。完整基准、完整 fault registry 与长稳保持发布必需，完整 driver 变更仍触发对应整库套件。
6. 首次组件性能测量依预冻结绝对预算建立实测候选基线；没有旧基线就不声称回归已比较，不用自身比较自身。基线晋升和后续预算变更保留理由、原始数据和独立复核。

## 影响与验证边界

本次没有已实现的数据库场景被删除或降低门槛；测量比较器、阈值和完整 workload/fault registry 不变。新组件套件当前仍 planned，数据库运行代码依旧不能无证据通过。本次仓库/API/harness 自测只证明文档和质量工具的约束，不证明 SQL、格式、性能、恢复或分布式已通过。

按切片开发可以提前暴露真实限制，代价是 alpha 能力必须显式受限，不能对外宣传完整 P0、全 PG 兼容、全格式支持或生产可用。
