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

## 图片描述关键词检索

状态：固定源/同一真实图片解码与Rust运行时关键词链路已通过非作者验收。

本节固定一个真实COCO image_id=397133及其5条caption。离线准备读取现有标注ZIP的固定member及
现有val2017.zip中的`val2017/000000397133.jpg`，只取这一张200576B图片，不扫描或解压全图包。
需要macOS自带`/usr/bin/sips`（ImageIO）实际解码；无该工具即拒绝，不安装新依赖。

```sh
COCO_SOURCE_ROOT=/Users/chad/dev/guradb-data/public-multimodal-20261025
GURADB_CAPTION_DIR=artifacts/coco-caption
.venv/bin/python scripts/prepare_coco_caption.py --annotations-zip "$COCO_SOURCE_ROOT/archives/annotations_trainval2017.zip" --images-zip "$COCO_SOURCE_ROOT/archives/val2017.zip" --output-dir "$GURADB_CAPTION_DIR"
docker run --rm --network none --memory 512m --pids-limit 128 -v "$PWD:/workspace:ro" -w /workspace guradb-rust:1.90.0 /workspace/target/debug/guradb query --config "/workspace/$GURADB_CAPTION_DIR/config.json" --sql "SELECT image_id, caption_id, caption, image_path FROM records WHERE caption LIKE '%kitchen%' ORDER BY caption_id ASC LIMIT 10"
```

结果粒度为一条caption而非去重图片：image_id都为397133，caption_id依次370509/372252/372765；
caption原文依次为`A man is in a kitchen making pizzas.`、`A baker is working in the kitchen rolling dough.`、
`A person standing by a stove in a kitchen.`。image_path均为`images/000000397133.jpg`，相对config目录定位真实JPEG。
完整JSON/exit0、源SHA与config/实际Parquet一致、truncated=false才算成功。改关键词为oven只命中370584，
zzqnonexistent返回空rows。匹配在Rust执行时完成，准备不接收关键词、不生成命中Bool。

SQL新增仅允许text列`LIKE '%关键词%'`，精确区分大小写、按Unicode字面子串匹配；关键词1–128个UTF8 bytes。
关键词内部的%、_、反斜线拒绝；仅外围两个%作为子串边界，不提供其它通配/转义。
直接NOT LIKE/ILIKE/ANY/ESCAPE、非text列、非字符串或列模式、空/超长模式均unsupported；函数等旧拒绝继续。
旧布尔组合NOT(caption LIKE ...)仍支持，区别于被拒的直接NOT LIKE语法。
单引号按SQL双单引号书写。NULL caption不会命中。原SQL16KiB、输出/内存/期限硬界不变。

准备只接受前节固定annotations成员SHA及JPEG SHA
`09e1d25c75f7879bdaa69c327fece5cabacd53939c8c2ef9e87f1c97a2e478c4`，
按caption_id排序从原标注取该图5条，保留image_id/caption_id/caption/file_name/image_path/width/height。
缺标注/图片、错误成员身份/关联、坏图片或解码尺寸不符均拒绝并清本次输出；已有输出路径不覆盖。
JPEG被实际解码为临时PNG并核640x427，临时PNG随后删除；输出仅小Parquet/config/source.json和原JPEG副本。
本例上界1图/5行/1MiB Parquet，图像读取1张<16MiB；原ZIP只读，完成可删本次GURADB_CAPTION_DIR，原媒体不删。
Rust只查询caption及图片定位，不读取像素、不做视觉识别、ANN、语义检索或外部文件访问。
图片路径和source.json记录准备时已校验的JPEG；CLI不在查询时复核该外部文件，移动/删除/改写后须重新准备或自行核图片SHA。
可在macOS执行`open "$GURADB_CAPTION_DIR/images/000000397133.jpg"`查看本次图片。

caption/标注归属COCO Consortium，按[COCO annotations CC BY4.0条款](https://github.com/cocodataset/cocodataset.github.io/blob/master/dataset/termsofuse.htm)。
图片归属与标注分开：原images条目license_id=4，链接[CC BY2.0](https://creativecommons.org/licenses/by/2.0/)，
原Flickr来源为http://farm7.staticflickr.com/6116/6255196340_da26cf2c9e_z.jpg；该条目未提供摄影者姓名，保留来源及未知项。
本例本机读取/解码不构成对其它图片授权或公开分发的认证，不把COCO的标注许可套到图像；无新图片下载或发布。

## 跨图片的描述关键词检索

状态：固定三图及原caption关联、实际解码与现Rust跨图查询已通过非作者验收。

复用上节同一prepare入口，新增固定`--sample three`；不传该选项仍是原单图5caption示例，输入/列/旧操作保持。
三图预设精确为397133（厨房）、252219（街道）、403385（浴室），各5条原caption，共15行、一个Parquet。
不提供任意ID列表/重复选择或全库导入；`--sample`其它值拒绝。

```sh
COCO_SOURCE_ROOT=/Users/chad/dev/guradb-data/public-multimodal-20261025
GURADB_MULTI_DIR=artifacts/coco-multi
.venv/bin/python scripts/prepare_coco_caption.py --annotations-zip "$COCO_SOURCE_ROOT/archives/annotations_trainval2017.zip" --images-zip "$COCO_SOURCE_ROOT/archives/val2017.zip" --output-dir "$GURADB_MULTI_DIR" --sample three
docker run --rm --network none --memory 512m --pids-limit 128 -v "$PWD:/workspace:ro" -w /workspace guradb-rust:1.90.0 /workspace/target/debug/guradb query --config "/workspace/$GURADB_MULTI_DIR/config.json" --sql "SELECT image_id, caption_id, caption, image_path FROM records WHERE caption LIKE '%street%' ORDER BY caption_id ASC LIMIT 20"
```

street严格命中image_id252219的caption_id107395/111433/114199/114511，路径images/000000252219.jpg；
将同一SQL关键词换bathroom，严格命中image_id403385的501985/507367/508369/510313，路径images/000000403385.jpg；
kitchen仍是image_id397133的370509/372252/372765，路径images/000000397133.jpg；zzqnonexistent为空。
所有caption是原源原文，包括大小写/标点/末尾空格，不清洗改写。完整JSON/exit0、source_sha256等于config/Parquet、truncated=false；
粒度仍每caption一行，重复image_id不是去重图片或相关性排名。关键词仍由既有Rust LIKE运行时计算，无引擎/SQL扩展。

三图JPEG总425263B：397133为200576B/640×427；252219为143225B/640×428；403385为81462B/640×511。
新增两图固定memberSHA分别1cf48bddb1bcab80d9f4d18514ae438c3e4f57d18e80c4fbea9d5d22396f514a、
11632ed3fb470d62f7fe5f0445c4f10ec91225c4a820c95d1c3946af9426d4c7；准备逐图实际ImageIO解码并核原标注尺寸。
只读这三个精确ZIP成员，不扫媒体库、全包解压/哈希或下载；总上界3图16MiB、200caption行/1MiB Parquet。
输出images下三份原JPEG副本、同一records.parquet/config.json及source.json中逐图身份/许可/decode记录；临时PNG即时删除。
任一图缺失/身份或关联不符、解码或后续写出失败，整次新输出回收；已有输出路径不覆盖。
图片定位仍为准备时快照，Rust只核Parquet，查询时不复核JPEG；完成可删除本次GURADB_MULTI_DIR，原ZIP只读保留。

caption按COCO annotations CC BY4归属；三图源metadata均license_id4/CC BY2，逐图FlickrURL及摄影者UNKNOWN单独写source.json，
不把描述许可推导为图像授权/公开发布认证。仍非视觉识别、语义/向量检索、规模或性能交付，不推进#138。

## 按图片返回唯一结果

状态：真实原caption投影集合及重复/NULL/类型/排序LIMIT边界已通过非作者验收。

复用上节三图/15caption准备命令与同一config。对投影列整行使用`SELECT DISTINCT`，
在Rust执行过滤→列投影→整行去重→输出列排序→LIMIT；不选最佳caption、不做图片视觉去重或相关性排名。

```sh
docker run --rm --network none --memory 512m --pids-limit 128 -v "$PWD:/workspace:ro" -w /workspace guradb-rust:1.90.0 /workspace/target/debug/guradb query --config "/workspace/$GURADB_MULTI_DIR/config.json" --sql "SELECT DISTINCT image_id, image_path FROM records WHERE caption LIKE '%kitchen%' ORDER BY image_id ASC"
```

kitchen严格一行`["397133","images/000000397133.jpg"]`；将WHERE改为
`caption LIKE '%kitchen%' OR caption LIKE '%street%' OR caption LIKE '%bathroom%'`，
ORDER BY image_id ASC得到252219/397133/403385三行及各自images/12位文件名路径；
在该排序查询末尾加LIMIT 2，必须只返回252219/397133两行，LIMIT在去重后生效。
无命中仍为空，完整JSON/exit0、source_sha256=实际Parquet/config及truncated=false才算本例成功。
原不加DISTINCT的caption明细仍保留重复image_id与原行语义。

支持现有Int64/Utf8/Boolean列（含NULL）的列投影/别名或默认*；按全部投影值组合去重，
NULL在去重比较中视为相同，NULL与空字符串不同，文本区分大小写。不提供仅按image_id选任意caption的隐式规则。
DISTINCT的ORDER BY仅可引用已投影输出列名/别名；隐藏输入列/别名原名、表达式或位置序号排序拒绝。
没有ORDER BY时行序未指定，不能依赖当前顺序分页。非DISTINCT排序规则保持原行为。
DISTINCT ON、函数/任意表达式投影、重复输出列名、其它原不支持修饰符明确unsupported，不解析后忽略。
原源/解码/池/SQL/输出/行数/期限边界保持，去重仍受32MiB DataFusion池限制、禁止spill，
预算不足明确失败；不得通过先LIMIT再去重或放宽预算伪造完整结果。
1000行预算计去重后的结果：未用更小SQL LIMIT且唯一结果超1000行时输出1000行、truncated=true；SQL LIMIT2本身不标预算截断。

媒体仍用前节固定三图与原许可/准备快照语义；本例新增的是Rust图片级投影集合，不新增媒体/模型/SQL服务，
原图解码与关联证据沿用，不把此结果宣称性能或完整发布通过。

配置只有source、sha256及timeout_ms三个字段；source相对配置文件目录，默认期限5000ms。
首跑已自动生成实际配置；若换自己的数据，sha256必须是自己原文件的真实摘要，不能使用占位值。

成功输出一个JSON对象，含源SHA256、列、完整结果行和是否截断。int64按十进制
字符串输出以保留精度。输入/SQL/执行失败只向stderr输出错误JSON且exit非0，stdout为空。
输出开始后遇管道关闭、超时或中断可能只写出部分JSON；消费者必须检查完整JSON及exit0。
SQL只支持单表列投影/别名、比较/AND/OR/NOT/NULL、本节受限LIKE、列排序和LIMIT；
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
