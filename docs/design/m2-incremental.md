# M2-S 受限显式触发同步

用户验收：操作者固定一个新 metadata SHA 与 snapshot，从当前已发布视图显式刷新，发布前旧视图继续可读；同 operation 重放只对账同一 run，不能改变目标。`progress` 返回 discovered/applied/indexed/published；发布沿用 generation/epoch CAS。

白名单：同一 Iceberg v2 表 UUID、root、唯一 schema、键与映射，目标必须是当前 metadata HEAD，沿完整 parent chain 从基点向前，所有新提交 operation=append。固定无分区 Parquet 和原 M1 类型限制；全量数据、特征与媒体读取遵循 M1 预算。拒绝 schema/分区变更、缺历史、回滚、换表、删除、rewrite、旧文件消失/属性改变/字节改变、重复键；不自动回退 Snapshot。

本切片验证文件增量，但执行全量 Snapshot 数据复制及 BM25/向量索引 rebuild；没有仅新增源读取或增量索引性能承诺。最多 32 次 parent 步进；历史校验最多 128 GET、32 MiB、30 秒，构建另一个相同预算。构建仍最多 32 文件、10000 行。源历史检查和新构建分别计量，不将其结果冒充性能提速。

run target 持久保存基点 run、固定源配置与检查依赖摘要。building 对应 discovered；ready 对应 applied+indexed；published 对应四进度全部达到目标。失败保留 target/error，不能重用同 operation 悄悄重试；须用新 operation。进程在 building 中止后同 operation 明确返回 building，需操作者诊断并重新发起；不宣称透明恢复。构建产物进入 ready 前再次比对已校验源文件哈希，以拒绝两阶段间替换。

验证使用独立 PyIceberg append 写入与扫描为真值，覆盖多次 append、缺父链、rewrite/delete/rollback、schema/UUID 变化和旧数据替换。旧视图保留与发布 CAS 复用 M1 控制面合同。生产 Continuous、分布式刷新调度、源 retention 协议及长期故障恢复仍未覆盖。
