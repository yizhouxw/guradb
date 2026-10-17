# M2 append 增量切片变更计划

验收：固定 append descendant 只向源 GET 新 Parquet；旧行从哈希固定 managed-copy 读取并继承 record_version。新增键与全量键冲突失败，旧特征/媒体变化失败；发布/replay/CAS 保持原协议。

不变量：INV-001/002/005/010/011；完整 parent manifests 与文件属性验证继续执行；上游旧 URI 字节替换检测仍需源完整性校验，不能以 metadata 属性代替哈希。

最小切片：source reader 的缓存层复用已验证副本，保留全量有界解码/索引 rebuild；索引增量、CDC、schema/delete/rewrite 不支持。复用依赖必须复制到新 run，旧 run GC 后新视图仍独立。

真值：新增源 GET 计数、继承版本、重复键及旧特征拒绝测试。预算保持 32 文件/10000 行及既有源/产物字节限制，不宣称索引或端到端提速。

故障：副本 hash 不符、两阶段源变化、构建失败、operation 重放维持 fail-closed；根任务运行完整门禁与独立复核。
