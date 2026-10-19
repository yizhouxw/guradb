# 产品功能与支持范围

GuraDB 的目标是把开放湖上的结构化记录、文本、媒体引用、向量和关系放在一致的数据视图中用于 AI 应用。当前适合小规模受控验证：只读 SQL、固定快照检索、简单关系扩展及可复现训练导出。不要将当前 alpha 用于高并发 OLTP、实时敏感业务事务或生产 SLA。

## 当前能力

| 能力 | 当前有界实现 | 限制或明确不支持 |
| --- | --- | --- |
| 数据接入 | M0 固定 Parquet manifest；M1 固定 Iceberg v2 metadata/snapshot | Iceberg 仅无分区 long/string/boolean Parquet 子集；不接受 position/equality delete、schema/partition 演进；未支持 Delta/Hudi/外部 Lance 连接器 |
| SQL | M0 单表 SELECT，列投影、比较过滤、ORDER BY、LIMIT，值参数 | 不支持 JOIN、聚合、CTE、函数、DDL/DML、业务事务；DataFusion 内部能力不自动开放 |
| 客户端 | M0 HTTP、可选本机 PG wire；M1/M2 HTTP、CLI、MCP | 两种服务未统一 SQL 执行；PG 限 psql 18/Psycopg 3.2.10 有界场景，不承诺 ORM、系统目录、扩展兼容 |
| 全文 | ASCII 字母数字小写分词，BM25；v2 三物理分片与全局统计 | 无中文/多语分词、短语检索或 PG 全文函数；v1/v2 分数不保证相同 |
| 向量与融合 | 精确平方 L2、显式构建 Lance IVF_FLAT、候选重排、BM25/向量 RRF | 模型/维数必须匹配；小分片可精确回退；未证明通用 ANN 提速/recall，无 pgvector ABI |
| Graph | 固定边表，一跳，in/out/both、类型和扇出预算 | 无多跳、跨数据集节点版本解析、邻接索引或 Cypher/GQL/PGQ |
| 多模态 | 外部生成的向量、媒体 URI/大小/SHA-256、受授权媒体副本 | 无媒体解码、OCR/ASR、视频抽帧或 embedding 生成 |
| 数据刷新 | 显式 snapshot；验证 append 历史后读取新增源文件 | 派生索引仍全量重建；无连续同步，不将 update/delete/rewrite 当 append |
| 托管写入 | 单机可信操作者，本地独占目录，固定 id/title/active append | 无公开业务写 API、跨主机 writer 或外部湖写回 |
| 训练 | 固定视图全部记录、seed 确定性 split 标签、manifest/Parquet、保留 pin | 无样本筛选、列投影、SQL 选样、DataLoader 或 epoch 续读；split 不会删除记录 |
| 运维 | dataset 授权复查、资源预算、pin/GC、状态快照、离线联合恢复 | 无内建 TLS/OIDC、行列策略、生产审计告警、HA/PITR 或跨机灾备 |

## 容量和可见性

M0 每查询扫描上限 32 MiB、解码 64 MiB、引擎池 32 MiB、结果 2 MiB/1000 行、运行并发 2、句柄 32、总超时默认 10 秒、终态保留默认 60 秒；配置只能降低硬上限，无 spill。每次完整读取并校验清单文件，尚无按需范围读取/裁剪/缓存扩展性保证。

M1/M2 有界合同包括最多 10000 行、32 个源文件、256 维向量、1000 搜索候选和目录总计 128 个 run；达到上限应停止评估并规划后续容量方案，不能删约束或静默漏读。更多预算见[能力清单](../../api/capabilities/v1.json)与各[运行说明](../design/m2-running.md)。这些是拒绝边界，不是吞吐或延迟承诺。

默认检索读已发布 read view。源提交、构建 ready、视图 published 是不同状态；数据已追加不等于搜索可见。查询固定版本，训练 pin 保护消费中的产物。M0 启动清单不自动跟随 M1/M2 的发布指针。

## 评估与后续方向

先用[安装示例](installation.md)验证 SQL，再按[使用指南](usage.md)评估自己的快照、特征和媒体。对不支持语法、维数、删除或演进输入必须观察明确失败；不能用“连接成功”推导兼容。

样本选择、读取扩展性、生命周期、多机和完整性能/故障/长稳是后续工作，见[路线图](../roadmap.md)。完整 release 门禁仍缺证据；组件测试、synthetic 负载或本地三个 worker 不能证明生产就绪。
