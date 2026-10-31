# ADR0048：固定Parquet的局部完整性与投影读取

状态：有限实现/非作者候选验收通过；2026-10-31。

旧路径继续完整源bytes验证。新显式parquet-read消费可信离线描述：来源总SHA是provenance；实际head/footer/selected chunks同强ETag+CR/CL+范围SHA核同，只授已读范围完整性。准备完整读取/转换/摘要与消费者局部读取请求、载荷、解码成本分账；不让离线抄写结果充运行期扫描。

选择已有parquet56/Arrow56的ChunkReader、ArrowReaderMetadata/ProjectionMask/rowgroups；自有稀疏片段只供已核bytes，洞读硬拒，不使用补零文件/完整缓冲区/隐式源回退。选中Page用SerializedPageReader核实际V1/V2/PLAIN+RLE，footer只作全schema/codec/总源rows和offset长度集合权威，不冒页版本认证。再仅解码所选片段。

组合共享既有Range HTTP验证内核，显式传同绝对deadline/remaining header allowance，最多8GET/512KiB累计body/64KiB累计头；旧object-range保持1GET/16KiB头。新launcher开关只扩到明确新命令，其余默认offline/两mount/固定本机none namespace不变。

支持/拒绝、顺序/类型、预算和信任源由用户页冻结。必要设计与实现前原读真值独立审查；真实HTTP读取范围+准确记录再正常H-M/单fresh安装/旧CLI-SDK兼容/owner终态。仅组件core-limited，不授一般下推/远端湖或整对象未读完整性。

实现时实读锁定库发现：standard Compact PageHeader binary长、Slice footer的generated list会在读取剩余bytes前按声明分配。传输512KiB不能充解析64MiB防护，因此添加现已锁/已缓存thrift0.17.0 direct dependency(default-features=false，Apache2，45286B/archive checksum核同，0下载/不扩server特性)。受限TInputProtocol wrapper共享无buffer cursor，所有语义/primitive委托官方，仅分配前peek/check与container/depth共同heap记账；read_string走受限bytes，默认skip走Self。Footer和选中PageHeader先官方typed预检并drop，再原解析相同不可变bytes，保守记账包括二次解析与Arrow，不自建通用Compact语法或给每阶段另64MiB。原rawFooter平面schema/type/crypto声明在有损转换前明确拒。必要设计与实现审查独立记录，不以旧86测试冒后修码。
