# 单机 Rust SQL alpha（有界核心用例已通过非作者验收）

本次一次切换为可信操作者在单机运行的单进程CLI，不启动网络服务。
配置只指定一份本地Parquet文件及其预先计算的SHA-256；表名固定records。
文件仅支持Int64、Utf8和Boolean列，不读对象存储、外部目录或其它文件。

首跑请在仓库根目录原样执行[README的准备与Rust命令](../../README.md)：
复用已有`scripts/alpha_acceptance.py --run-dir artifacts/first-run`，它在新目录中生成
4行合成Parquet与`good.json`，自动计算并填写SHA256，且完成既有黑盒检查；不需要猜文件来源。
目录必须是仓库artifacts下尚不存在的相对目录，已有目录会拒绝，不覆盖文件。
随后README命令使用`/workspace/artifacts/first-run/good.json`读取同一份输入，过滤active、
按rank升序取两行，确切rows为`[["r0", null, "0"], ["r1", "first", "1"]]`。
JSON源摘要应与自动生成的good.json相同，truncated=false。

## 真实COCO元数据入口

状态：现有源小样本已通过非作者实际验收；范围仅本节固定输入。

已有COCO2017 `annotations_trainval2017.zip` 时，可离线准备一个32行元数据样本；
脚本不下载文件、不打开图像、不执行Rust或复制黑盒验收runner。先按README建立已有锁定Python环境及Rust binary。
本机已验源位于下列COCO_SOURCE_ZIP；其它机器将该变量改为自己已持有文件的绝对路径。
所有命令从仓库根目录执行，GURADB_COCO_DIR为artifacts下尚不存在的相对目录。

```sh
COCO_SOURCE_ZIP=/Users/chad/dev/guradb-data/public-multimodal-20261025/archives/annotations_trainval2017.zip
GURADB_COCO_DIR=artifacts/coco-metadata
.venv/bin/python scripts/prepare_coco_metadata.py --source-zip "$COCO_SOURCE_ZIP" --output-dir "$GURADB_COCO_DIR"
docker run --rm --network none --memory 512m --pids-limit 128 -v "$PWD:/workspace:ro" -w /workspace guradb-rust:1.90.0 /workspace/target/debug/guradb query --config "/workspace/$GURADB_COCO_DIR/config.json" --sql 'SELECT image_id, file_name, width, height FROM records WHERE is_landscape = true ORDER BY image_id ASC LIMIT 5'
```

准备入口只读`annotations/captions_val2017.json`一个标注成员（3,872,473B，小于4MiB），
要求SHA256为`afe3b30e403dd7f228e2373023abbd60042a6e10ec6874d3652df034d289ebb9`。
这是本例已验证的固定输入身份；其它成员内容/版本明确拒绝，不承诺通用COCO版本兼容。
ZIP其它成员和整个archive的远端字节身份不在本例验证范围。

按原JSON images数组顺序取前32条，image_id/file_name/width/height/image_license_id分别来自
id/file_name/width/height/license；source_ordinal仅记录原数组0起位置，is_landscape由width>height派生。
列限Int64/Utf8/Boolean。完整JSON会被解析，其中caption字段不被选取、查询或复制，图像文件不打开。
输出目录内生成records.parquet、自动填写实际Parquet SHA256及5000ms期限的config.json、
记录来源/成员摘要/归属/变换的source.json；样本限制1MiB/1000行，不是全COCO数据导入。

成功准备exit0，随后Rust命令必须exit0且完整JSON的rows严格为：

```json
[["17627","000000017627.jpg","640","480"],["37777","000000037777.jpg","352","230"],["41888","000000041888.jpg","640","480"],["87038","000000087038.jpg","640","480"],["143931","000000143931.jpg","640","480"]]
```

columns依次image_id/int8、file_name/text、width/int8、height/int8（int8表示64位整数），
truncated=false，source_sha256等于config.json的sha256与实际Parquet摘要。这只是上述32条样本内的前5行。

已有输出路径（包括文件/链接）明确拒绝且不覆盖；请换一个新目录。缺失源、无效ZIP/指定成员、
超限或不匹配成员身份均exit非0并给明确错误，创建输出前即拒绝；准备写出失败时清理本次派生文件。
源始终只读。完成后可删除本次生成的GURADB_COCO_DIR，勿删除或移动原ZIP/媒体。
没有旧目录迁移，也没有网络服务、权限或pin/lease机制；查询预算/失败恢复沿用下文既有CLI合同。

归属：COCO Consortium，COCO2017 Dataset v1.0（2017/09/01）。
[官方条款](https://github.com/cocodataset/cocodataset.github.io/blob/master/dataset/termsofuse.htm)将annotations/website
列为[CC BY4.0](https://creativecommons.org/licenses/by/4.0/)，图像版权/使用条件另列；本例只作元数据抽样、字段投影和Bool派生。
不证明图像存在性/像素解码、caption查询、媒体完整性、检索、规模、性能或完整产品发布，不推进#138。

配置只有source、sha256及timeout_ms三个字段；source相对配置文件目录，默认期限5000ms。
首跑已自动生成实际配置；若换自己的数据，sha256必须是自己原文件的真实摘要，不能使用占位值。

成功输出一个JSON对象，含源SHA256、列、完整结果行和是否截断。int64按十进制
字符串输出以保留精度。输入/SQL/执行失败只向stderr输出错误JSON且exit非0，stdout为空。
输出开始后遇管道关闭、超时或中断可能只写出部分JSON；消费者必须检查完整JSON及exit0。
SQL只支持单表列投影/别名、比较/AND/OR/NOT/NULL、列排序和LIMIT；
JOIN、函数、聚合、子查询、写入、参数、外部路径、HTTP/PG端口均暂不支持。
初读或发布前复核时摘要不符、缺文件及损坏/不支持Parquet均失败。
查询只消费初读已验bytes；不承诺检测两次摘要校验之间修改后又恢复的文件事件。

资源作用域：每次调用一个进程，读取有界不可变bytes，Arrow批次及DataFusion
内存池只归本次调用；无后台worker、网络listener、持久目录、pin/lease或授权缓存。
默认/硬上界：源32MiB、解码64MiB、DataFusion池32MiB、输出2MiB、1000行，
SQL16KiB、配置16KiB、期限5秒（可设1–10000ms）。不允许磁盘溢写。
超时exit124，SIGINT exit130，进程退出回收本次所有线程、文件与内存；
成功/失败/取消后均可再次运行。输出在全部执行及源复核通过后才发布。
SHA256绑定的是原始Parquet文件bytes，不建立新的记录版本或目录发布协议。

旧Python在线索引、HTTP/PG、分布式worker、训练导出等demo已在真CLI跑通后实际删除，
本alpha不继续支持。历史设计/失败仍是历史，未来Rust能力见当前手册。
不得将此有界fixture通过宣称多租户、海量规模、兼容全域或可生产发布。

本次真实自测：独立四行Parquet核列投影、过滤、排序/LIMIT、源SHA256，坏摘要、
缺输入、损坏Parquet、函数SQL均拒绝，恢复原输入可重跑。真实进程测试验证输出
管道关闭、输出阻塞时超时/SIGINT及PID退出；16MiB源在打开期间改变时明确失败，
恢复原bytes再次成功。完整性能、长稳、覆盖率及发布未验证。
