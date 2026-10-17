# ADR 0012：有界 P0 扩展与本地 worker 切片

- 状态：接受有界实现策略，验收结论以本轮最终commit报告为准
- 日期：2026-10-17
- 前置：ADR0004/0006/0007/0011，路线图M2与M3

## 决定

保留M0 Rust/DataFusion SQL与M1 Python控制/检索边界，增添可选Lance IVF_FLAT派生索引、固定视图typed-edge一跳、验证append历史后的显式增量读取与索引 rebuild、单机可信受控托管append和MCP薄HTTP适配。

Lance固定pylance0.39.0，与Arrow22共同实测；native构建/查询使用可终止子进程，维持稳定键和revision、不可变dataset版本/文件摘要。源事实保持唯一权威，ANN不接受独立业务写。

托管append以独立PG意图/源generation和贯穿本地catalog提交的flock限定单机提交权，源码目录不接受旁路writer。源提交未知先对账，与目录read view发布CAS分别验证；没有将本地锁认证为跨机器fencing。

本地三worker按记录分片执行scan、精确向量、Graph和训练转换，统一候选与全局归并。Tantivy全局统计和Lance ANN仍单节点；不以该切片标记完整M3，更不承诺跨节点HA、spill/复杂exchange。

## 代价和迁移

显式刷新复用哈希固定的旧副本，只向源读取新增 Parquet，并继承旧行版本；索引仍全量重建。源 identity 检测及旧 bundle 迁移边界见增量设计，不宣称恶意上游下零读取仍可证明旧源字节完整性。每请求启动worker带来序列化/启动成本，必须报告实际测量，不能拿并行进程数宣传提速。
旧M1无ANN产物兼容；新能力通过显式请求开启。托管schema独立，操作/恢复和白名单见[运行说明](../design/m2-running.md)。

新增依赖：pylance0.39.0、numpy2.3.5、lance-namespace0.13.0、lance-namespace-urllib3-client0.13.0固定于requirements-m1.lock；包license metadata检查在本轮依赖报告。PyIceberg从独立fixture依赖扩展为托管writer实现，仍由独立reader和原custom reader交叉验证；全量分发SBOM及项目许可证保留为生产前义务。
