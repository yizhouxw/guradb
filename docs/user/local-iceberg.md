# 本地Iceberg v2固定快照（本机受限）

可信单用户，本地明确table root，调用者指定metadata相对路径、其SHA256与snapshot ID；Rust自行解析真实metadata JSON→manifest-list→全部manifest，应用data-file ADDED/EXISTING为live、DELETED不读，1或2个live Parquet才支持；不能Python挑文件或LIST猜latest。官方PyIceberg0.10.0的实际A15 append4→双19→全overwrite4为互操作真值，可能有空DELETE中间snapshot，不假称恰两条历史。

新增只读`iceberg inspect --table-root <physical> --metadata <relative> --metadata-sha256 <hex> --snapshot <id>`，冻结实际完整readset；`iceberg query`同参数加`--readset-sha256 <inspect-observed-pin> --sql <SQL>`，先核完整readset pin再执行同Rust SQL，结束重核所有链字节。inspect只报告实际观察的字节，不认证先前未被替换；metadataSHA单独不加密绑定子文件。query的显式readset pin用于拒绝调用前/执行期manifest或data替换，不能拿新观察值偷偷覆盖旧pin。

readset SHA v1：UTF8域头`guradb-iceberg-readset-v1\n{table_uuid}\n{snapshot_id}\n{schema_id}\n`，接按relative path字典序的每个已读文件`relative_path\0sha256_hex\n`。含metadata、选中manifest-list/全部manifest及全部1–2个live Parquet；路径ASCII无NUL/换行，重复引用拒。相对路径以metadata.location原file根为基，显式physical table-root只负责本地重定位：引用必须同一逻辑file根且组件边界匹配，映射其相对路径到physical-root；不直接打开host绝对URI，不截basename。不允许远端scheme/authority、percent编码/query/fragment、..、空组件/绝对metadata参数、任一symlink或越根。原始URI字节及文件SHA绑定，移动小表到/data仍同pin。

format-v2、unpartitioned（单空spec0）、单固定schema（ID与每列fieldID>0唯一/名称顺序/long-string-boolean类型/required性质与Parquet真实fieldID一致）、无nested/evolution/sort order。最多8 snapshot记录，显式选ID；当前snapshot不替换选择。源保留与immutable-child由使用者负责，无owned托管/pin/GC/catalog/云或Range承诺。Avro OCF首片仅null；默认gzip/deflate及其他codec均拒（官方parser的deflate解块无输出限，不假称allocation cap覆盖该处）；Parquet首片uncompressed/snappy，row-level position/equality delete、delete manifest、0或>2live、分区/未支持格式全部拒。无检索/样本/MCP湖入口，directconfig/view/managed原白名单不变，不把旧features沿新湖源用。

新增链总encoded字节≤2MiB，metadata/list各≤256KiB、manifest每份≤512KiB，选中manifest≤2、每份entry≤32/总64，root内路径≤16层/每组件≤255字节/总≤4096；有限直接文件读取不扫描目录。全snapshot source总≤32MiB/声明decode总64MiB及retained Arrow buffers总64MiB/output2MiB/32MiB pool/no spill，原Rust512MiB4CPU10s与aggregate input/group200不扩。最多捕获metadata+list+2manifest+2data共6文件，成功发布前重读同集合最多12次bounded文件读取，官方Avro parser allocation cap设2MiB并在解块前拒非null codec，避免压缩解块绕过cap；实际边界仍须独验。取消/失败无成功输出/不写表，原hash-pin变化给source_changed，非法格式路径与未授语义明确拒。

准备工具只在fresh离线环境：PyIceberg0.10.0+SQLAlchemy2.0.43，借现有Arrow22/NumPy只读package，不改CLIP/SDK/主venv，不装pyarrow extra/pyiceberg-core或模型。生产parser仅官方Apache Avro Rust0.20.0/default-features=false（依赖锁/许可证/字节预算待预检），在线仍Rust。依赖payload新获取总≤32MiB/180s/单60s、newowned≤1GiB/唯一fresh安装消费者；当前已通过受限候选语义验收，非完整Iceberg/M2/生产湖或发行。

## 双live数据文件（本机有限组件验收）

此合同仅将同一个显式固定snapshot扩为1或2个live Parquet。0或>2仍拒绝，ADDED与EXISTING不按本次snapshot ID过滤，DELETED不读；全部manifest所给live集合按相对path排序完整读取并逐文件核physical fieldID/schema/rows/codec。第二文件缺失、同尺寸替换、错fieldID、越根或symlink均整次拒绝，无成功payload；WHERE/LIMIT不允许掩盖无效文件。

原单文件JSON输出与source_sha256（该Parquet字节SHA）保持。双文件新增source_identity=`iceberg-data-files-v1`及有序source_files数组（path/sha256/size_bytes/record_count）；source_sha256为SHA256：UTF8域头`guradb-iceberg-data-files-v1\n{table_uuid}\n`后接按相对path字典序各`relative_path\0sha256_hex\n`。这是完整双文件集合的域分离摘要，不能拿首文件SHA冒整表或沿用旧feature/sample绑定。source_files与完整readset均含两个数据文件，旧readset-v1算法自然纳入全部路径，不无声重解释旧pin。最后重核同一完整集合；两次校验间修改后恢复不承诺侦测。

整次source总32MiB、Parquet声明decode总64MiB与retained Arrow buffers总64MiB、output2MiB、DataFusion pool32MiB/no-spill、512MiB4CPU10s均不变，不能逐文件重复领取。Q09 input/group200在拼接完整原始行之后、WHERE/LIMIT前核。metadata链总2MiB、2manifest/64entry等原界不变；readset只从最多5扩为6文件（metadata+list+2manifest+2data），捕获+发布前重核最多12次读取；inspect也验证两个文件，不把未解码内容标支持。

独立官方PyIceberg0.10.0真实append：原A15 append4→双19，再overwrite4；使用writer提供的确切metadata/snapshot/pin，旧A15与旧双19仍固定可读，保留旧child文件仍caller责任。COUNT、完整原行（含重复）、过滤与单列group须同独立原始行真值。新双文件能力需要本轮另名`guradb-iceberg-twofile-preview-macos-arm64-docker-linux-arm64.pyz`及同名.json sidecar的preview包；旧单文件包不冒支持。无目录扫描、Python生产选文件、分区/evolution/delete支持、云/同步或MCP湖扩展。非作者已从官方原源与独立真值完成27条真实CLI验证，包括完整原行/旧pin、NULL重复/类型与全次预算、第二文件错且LIMIT0不能掩盖。此为有限组件能力，正常PR/精确main和安装资格独立记账。

## 显式版本的读取

已有符合上述白名单的真实Iceberg表即可读取，不要求消费者安装PyIceberg；官方writer仅工程准备。已验writer为PyIceberg0.10.0/SQLAlchemy2.0.43/Arrow22/NumPy2.5.4，表属性显式`format-version=2`、`write.avro.compression-codec=null`、`write.parquet.compression-codec=snappy`。PyIceberg默认gzip/deflate不在本片支持范围。完整overwrite可有中间DELETE snapshot；选择其中0live者会按本片1–2live约束明确拒绝，不冒行级删除支持。源生成可参考[官方PyIceberg API](https://py.iceberg.apache.org/api/)，准确的历史snapshot ID和metadata版本由其writer返回；不遍历目录猜最新。

按[预览安装](local-preview.md)安装本片具名`guradb-iceberg-preview-macos-arm64-docker-linux-arm64.pyz`到新PREFIX（实际SHA和源码身份取相邻同basename.json清单，不覆盖旧包）。USER_DATA包含真实`table/`，METADATA设置为writer提供的确切metadata相对路径，METADATA_SHA为可信版本的SHA256，SNAPSHOT为明确选中的正整数ID，READSET_RECEIPT为自己尚不存在的输出文件：

```sh
"$PREFIX/bin/guradb" --data-root "$USER_DATA" iceberg inspect --table-root /data/table --metadata "$METADATA" --metadata-sha256 "$METADATA_SHA" --snapshot "$SNAPSHOT" > "$READSET_RECEIPT"
READSET_SHA=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["readset_sha256"])' "$READSET_RECEIPT")
"$PREFIX/bin/guradb" --data-root "$USER_DATA" iceberg query --table-root /data/table --metadata "$METADATA" --metadata-sha256 "$METADATA_SHA" --snapshot "$SNAPSHOT" --readset-sha256 "$READSET_SHA" --sql 'SELECT COUNT(*) AS total FROM records'
"$PREFIX/bin/guradb" --data-root "$USER_DATA" iceberg query --table-root /data/table --metadata "$METADATA" --metadata-sha256 "$METADATA_SHA" --snapshot "$SNAPSHOT" --readset-sha256 "$READSET_SHA" --sql 'SELECT image_id,COUNT(*) AS captions FROM records GROUP BY image_id ORDER BY image_id'
```

先检查inspect exit0与完整JSON再使用pin；保存此前可信readset，不在变更失败后自动inspect覆盖旧pin。A15/B4实际分别COUNT字符串15/4、group每媒体5-5-5与1-2-1；自有表按自己的完整原始行核对，image_id示例仅图文schema适用。query响应仍columns/rows/truncated/source_sha256，加table_uuid、snapshot_id、schema_id、metadata_sha256、readset_sha256与路径/文件摘要；确认所选ID和完整来源，不用current替历史ID。Rust没有写表、回收/保留或同步服务，使用者需保留旧snapshot所引文件；本机preview不是完整湖认证。
