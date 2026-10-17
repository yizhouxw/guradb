# 本地 worker 协议与检索执行计划

状态：进行中；属于 local-p0-integration，原始 base 0b3af06；共享 implementation worktree，不单独提交。

验收：固定视图的3个真实进程执行检索，全局候选窗口和RRF保持单节点真值；ANN查询在各worker上按键分区预过滤，同一不可变Lance索引。全文使用共享Tantivy全局统计索引按键归属结果，明确不是物理全文索引分片。训练worker验证实际分配的托管Parquet文件并转换本片样本。空片正常完成；错误、非法nprobes、超时、取消、结果协议不匹配整项失败。

支持：本地主机可信文件任务，最多3 worker、输入输出各32MiB、512MiB每worker、原deadline；无跨机器HA、物理全文分片、spill和任意exchange。共享索引查询不宣称索引横向扩容。

风险：INV001-012相关；plan要求contracts/functional/harness-tests/performance-smoke/policy/python/repository/stability-component。完整套件由主任务集成，本切片先跑独立契约。已有其他代理文件保持归属，不stage覆盖。

恢复：本切片没有事实写入/持久格式升级；worker临时文件随任务清理；运行中取消收割整个进程组。外部源和目录提交不在范围。

验证：单节点search对比独立进程执行，独立L2排序与ANN全探针召回，全文不平衡词频、融合窗口、过滤、空片和非法请求。协议错误使用明确Failure，不泄漏KeyError/TypeError；运行时性能成本留给主任务真实driver，不手填基线。

首个可验证训练实现：每worker接收自己键分区的特征行，读取全部固定Parquet文件，仅转换属于自己的键，并验证读取事实值与bundle完全一致。文件读取有PID/文件数/字节计数，属于按键分配的真实文件读取；当前每片重复读取同组文件，尚未实现物理文件互斥分配。单文件可供三个worker工作但没有IO缩减承诺。

后续已实现物理serving分片：Snapshot build阶段按稳定键轮转写3个独立Parquet（完整行/特征/媒体/record_version JSON）；每片足够训练样本时独立构建Lance IVF_FLAT目录，查询不重建。worker仅读本片Parquet；训练转换因此实现互斥文件任务分配。旧bundle无shards时沿用上述兼容路径。小片不足16*partitions显式exact-small-shard回退，统计中公开，不伪称ANN。

本地证据命令：`.venv/bin/python -m unittest tests.contracts.test_distributed -v`，真实三PID、旧bundle全文/精确/ANN/融合/过滤同真值、3独立ANN分片全探针独立L2排序、每worker唯一serving文件训练、空片/非法nprobes。完整门禁/性能/故障报告由主任务继续集成，未提供跨机器证据。
