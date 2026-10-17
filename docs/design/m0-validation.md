# M0 验收与义务映射

这些测试执行真实二进制、Parquet、HTTP、S3 与 PG18；验证边界是[详细设计](m0-parquet-http.md)的单进程切片。完整 registry 中的分布式、索引发布、写入、GC、训练等仍未覆盖。

| 义务 | 实现/测试证据 |
| --- | --- |
| INV-001 固定数据/视图 | catalog 固定 manifest SHA 派生 revision/view；跨文件 PyArrow 真值、S3旧版本读取、固定分页、重启同视图 |
| INV-002 对象与身份 | storage 精确 key/version GET+长度/SHA；common 冻结类型化键编码向量。M0 无键源使用 revision/fragment/ordinal 合同，尚无索引去重/跨版本键复用 |
| INV-007 授权 | gateway 每请求及执行点读 allowlist；跨租户/主体、缓存撤权、配置损坏关闭访问、HMAC游标绑定与篡改测试 |
| INV-008 预算/取消 | 扫描/解码/结果超限；真实S3暂停下排队/运行取消、超时、恢复；TTL/句柄容量；有限引擎池且禁止spill |
| INV-010 格式边界 | manifest版本/未知字段/重复列/危险路径/类型拒绝；坏footer/schema、symlink、对象覆盖/缺失；独立PyArrow读写互操作 |
| INV-012 SQL/接口 | PostgreSQL18 C collation差异；NULL、布尔、排序、极端int8、参数/注入；多语句/CTE/副作用/文件函数/锁/事务/写入等负例；实际响应按OpenAPI验证 |

功能 driver：[tests/functional/m0.py](../../tests/functional/m0.py)。独立真值不使用服务端编译器；PG种子数据由输入行生成，非服务端结果回灌。默认 fixture20行2文件及未列入清单的额外对象，版本化桶覆盖测试必须仍返回固定历史数据。

性能 driver：[tests/performance/component/m0.py](../../tests/performance/component/m0.py)。8192行2文件，固定生成规则seed=0，每次全扫描排序返回前1000行且显式truncated。5个新进程，每个cold/warm各1次，共10次请求，逐次对照PyArrow输入真值；冻结预算单次端到端≤10s、进程VmHWM≤512MiB、逻辑对象读取2次且字节严格等于清单。记录硬件/锁文件/输入对象摘要、吞吐、延迟、RSS、构建耗时和原始样本。cold仅指新进程，无本服务数据缓存，不清除宿主/S3页缓存。共享Docker与CI结果只建立M0初始smoke候选，未做历史回归比较，不等于产品规模基线；后续性能变化需受控同环境对照。

故障 driver：[tests/faults/component/m0.py](../../tests/faults/component/m0.py)。真实覆盖同长度对象/删除/恢复、授权撤销/恢复、暂停S3服务导致远程I/O阻塞、排队和运行取消/终态不倒退、超时/容量恢复、进程重启/旧句柄失效、TTL与容量。记录seed=0、按序注入/恢复和断言trace，失败非零退出。组件不调用完整registry校验器伪装分布式通过。

Rust gate 使用固定容器执行 fmt/clippy（警告视为错误）/test --locked。功能构建正常可执行文件，避免误将cargo test生成的测试壳作为服务。Python3.11/3.14安装各自锁文件；本地实际版本见执行报告，未在本机执行的矩阵只由Actions验证。CI上传整个run目录，包含driver原始证据；task-finish归档的harness报告/命令日志中有证据路径，但不替代外部长期产物归档。

已知限制：扫描/解码/结果均有应用层上限，库内部临时分配不是硬RSS隔离；单批解码/引擎任务存在协作取消边界。S3计数是成功的逻辑对象读取，SDK重试及HTTP wire请求不计入；无范围读取/缓存。数据、查询句柄、索引、外部版本保留和进程持久性分别解释，不承诺未实现语义。内部alpha不作为生产服务部署。
