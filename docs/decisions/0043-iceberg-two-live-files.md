# ADR0043：本地固定Iceberg快照的双live完整读取（已接受，有限组件已验）

在ADR0042的真实生态writer与同Rust SQL路径上，将live数白名单从恰1扩为1或2。完整ADDED/EXISTING集合按相对path稳定排序，不能按entry的旧snapshot ID漏掉保留文件；DELETED不读。不扩分区、schema、删除或远端语义。

原单文件输出/source字节SHA及readset-v1不变。双文件新增source_identity与完整source_files，source摘要按用户手册的独立域/UUID/排序path+子SHA计算。readset-v1本已聚合所有路径，双文件仍同算法，完整链捕获与成功前核同；仅readset最多5→6/双读10→12适配第二data文件，不放宽byte/内存/CPU/时限。

每文件先物理schema/行数/codec校验，全source32MiB/声明decode64MiB/Arrow buffers64MiB累计后送共享SQL；aggregate200在完整输入核，不用WHERE/LIMIT掩盖第二文件错误。官方A15 append4→19/overwrite4与旧快照原行、第二文件错误及全次预算由非作者独立验证；新增能力仅本受限来源，不给全Iceberg/M2或规模资格。

规范依据：[官方Iceberg specification manifests](https://iceberg.apache.org/spec/#manifests)，v1–v3的status 0/1为live、2不进入scan，manifest可被后续snapshot复用；本片只format-v2，不沿当前spec扩v3/v4。
