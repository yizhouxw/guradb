# M2-V：内部 Lance ANN

状态：实现中；待本轮真实门禁，非完整生产检索。

固定 pylance 0.39.0（Apache-2.0）、PyArrow 22.0.0，使用 IVF_FLAT，保持源逻辑键与 revision 列，禁止物理 rowid 作为外部身份。
Snapshot target 可选 `ann: {"partitions": 8}`，分区 1–64 且不超过行数/16。旧 M1 bundle 不包含 ANN 继续支持 exact；ANN 请求缺索引明确失败。
每个 read view 新建不可变 Lance dataset/index，固定 dataset version、逐文件摘要和源 revision；所有文件纳入发布前验证与 pin/GC。
查询 `vector_index: "ann"` 和可选 `nprobes`（1–partitions），默认最多探测 8 partitions；候选最多1000。
先应用相等过滤，再候选截断，使用源双精度向量精确重排。BM25 + ANN 沿用全局候选窗口 RRF，响应明确近似模式/探测与候选数。

功能：固定 seed 独立 exhaustive L2 真值，精确重排、过滤、同分稳定排序、模型拒绝、索引缺失/损坏拒绝。
重建/压实测试将相同行重排或移除后重新构建，必须只返回新视图中的逻辑键与版本；不支持对已发布 Lance 进行原地 mutation。
性能固定8192行、16维、seed17、8分区，8 probes时 recall@10>=0.95，记录4 probes的实际recall与延迟，不声称低 probes 必然达到门槛。
记录build<=60秒、query<=10秒、索引字节/源向量字节放大，冷进程/暖进程和OS缓存限制。native构建/查询在独立进程执行，取消/超时杀进程组并回收。
API依据 [Lance vector search](https://lance.org/quickstart/vector-search/)，实际调用以固定安装版本测试为准。
