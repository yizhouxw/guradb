# M2-G 有界 typed-edge 一跳关系扩展

## 变更计划与验收

用户可观察验收：固定 bundle 的边事实给出与独立关系选择/连接真值一致的一跳路径；方向、类型、稳定边身份和记录版本可核对。高扇出、边数超限、取消和超时明确失败，不返回部分结果。

最小切片：`modules.index.graph.expand(bundle, request, budget)`，无派生邻接存储或持久布局迁移；沿用 M1 bundle、逻辑键和 revision。验证独立真值、int8 字符串输入、类型错误、NULL、环/自环、重复 seed、排序、取消与预算。只修改 Graph 算子、对应测试和本文档；整体服务接入另由调用方实现。

不变量：单次调用仅使用传入 bundle；每个证据保留边 logical_key 和 revision，不使用物理 rowid；budget 在验证、扫描、输出阶段持续检查。最多扫描 MAX_ROWS=10000 行，最多 128 seeds，最多 1000 条路径，每 seed 最多 1000 条路径；超限 fail closed。时间沿用 Budget deadline；额外结果内存有界，输入 bundle 内存计入 M1 artifact 上限，不另复制边表。

## 请求与结果合同

请求必填 `source_field,target_field,type_field,seeds,type`，可选 `direction`（out 默认、in、both）、`max_edges`（默认100，上限1000）、`max_fanout`（默认100，上限1000）。拒绝其它字段。端点字段必须同型且为 text 或 int8，类型字段为 text；三字段必须互异。seeds 是1至128个同型非空值，不允许重复；type 是非空 UTF-8 字符串。文本值最多4096 UTF-8字节。int8 支持安全 JSON integer 和规范十进制字符串，超出 JSON 安全整数范围必须传字符串；bool 不视为整数。

边表中的端点和类型必须非空、符合声明类型。即使坏行不匹配 seed/type，也明确拒绝整个请求。edge logical_key 全表唯一且非空，记录版本为 bundle revision。端点是本数据集同一 revision 内的标量节点命名空间；本切片不接受跨数据集引用、外部节点表或独立节点版本解析，因此不承诺外部节点存在性验证。

返回 `paths,read_context,stats,truncated:false`。路径含 `logical_key,record_version,source,target,type,seed,neighbor,direction`；int8 对外统一十进制字符串。排序按 edge logical_key、seed 输入值的 canonical 顺序、遍历方向；与物理行序无关。both 的自环对同一 seed 只发出一次 out 路径；两端均在 seeds 的普通边会发出两个不同遍历路径，均计入边数与各 seed 扇出预算。边数预算计路径证据数，而非去重边数。无静默截断、无多跳、无 SQL 图语法、无邻接物化、无图算法、无独立 Graph writer。

## 证据与生产缺口

`tests/functional/graph.py` 提供独立关系真值和预算/取消负例，`tests/contracts/test_graph.py` 固定请求拒绝合同。局部算子测试不证明 HTTP、真实三 worker 归并、全库故障或生产发布；这些证据必须由集成任务实际运行并单独报告。扫描复杂度 O(rows + paths log paths)，无规模性能 baseline、持久邻接、跨 worker 全局预算/取消、节点外键或生产 SLO 声明。
