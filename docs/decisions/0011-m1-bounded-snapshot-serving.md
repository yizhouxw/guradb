# ADR 0011：M1 有界 Snapshot 服务化

- 状态：接受，限定 M1 单节点 alpha；本地门禁以任务最终报告为准
- 日期：2026-10-17
- 前置：ADR 0002/0003/0004/0006/0007/0010；路线图 M1

## 决定与取舍

以显式固定 metadata-location 实现第一个 Iceberg v2/Parquet Snapshot reader，不提前接入完整 REST Catalog。先拒绝 position/equality delete、schema/分区演进等未覆盖语义，按字段 ID 验证所有文件。独立 PyIceberg 0.10.0 创建/读取真值；生产 reader 用 fastavro 1.12.1 与 PyArrow 22 有界解析，不以自身产物作为唯一互操作证据。规范依据 [Iceberg specification](https://iceberg.apache.org/spec/)。

保留 M0 Rust/Arrow/DataFusion 的 SQL 执行基线；M1 新增 Python 的操作者编排、PG 控制面和 scan/search/export 服务，使用 Tantivy 0.26.0 的 Rust Python binding 与精确向量，不先写额外 Rust FFI/自定义 DataFusion 检索节点。这使 Snapshot/发布/训练闭环可以在有界负载下独立验证，代价是额外的 Python 依赖与进程接口。Python 生产代码按原模块归属分配，增加真实 AST import DAG、依赖锁与静态编译检查；不拿 Cargo lint 证明 Python。索引参数与导出持久合同写入[详细设计](../design/m1-snapshot-serving.md)，后续迁移到原生执行器必须保持身份/视图/排序并重新验收成本。

M1 scan/search/export 使用明确的 HTTP 契约，SQL 子集继续通过 M0 独立运行；不是通用 SQL/检索融合引擎，也没有第二套客户端直连/授权旁路。客户端只访问 HTTP，PG operator 属可信管理入口。采用PG18小目录事务/CAS、构建generation fencing、发布结果未知按operation/run对账、固定view任务与训练pin。源写入与目录发布fencing分别属于不同协议，本切片没有源写操作，不能以目录fencing宣称源提交安全已验收。

所选快照完整依赖复制到哈希固定的受控产物目录，发布前核验，查询/训练pin与retiring在PG锁下排他。媒体通过同一HTTP身份授权下载。导出按固定身份/seed确定split；不把metadata或索引置为独立业务写入权威。

## 验证与限制

真实PG/S3/HTTP/CLI、PyIceberg/PyArrow互操作、精确L2/RRF/训练真值、负例和发布/GC/取消/撤权/重启注入分别在组件门禁执行，映射见 [M1验收](../design/m1-validation.md)。完整P0、ANN、Graph、增量、托管writer、分布式/HA与生产release均待后续阶段。

本次新增独立PG schema v1，不迁移已有M0清单；显式init，不自动降级/删表。恢复必须同时保留PG目录、published/pin与完整产物目录，代码revert不等于数据回滚。新本地提交不自动推送，远端CI仍待授权后验证。
