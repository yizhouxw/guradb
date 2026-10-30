# 单机 Rust alpha（有界核心用例已通过非作者验收）

本次一次切换为可信操作者在单机运行的单进程CLI，不启动网络服务。
配置只指定一份本地Parquet文件及其预先计算的SHA-256；表名固定records。
query文件仅支持Int64、Utf8和Boolean列；媒体证据入口仅允许下节显式绑定的本地JPEG，不读对象存储。

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
1000行预算计去重后的结果：未显式指定SQL LIMIT且唯一结果超1000行时输出1000行、truncated=true。
显式LIMIT≤1000按该限制返回，不因SQL LIMIT本身标预算截断；LIMIT>1000仍受1000行预算，超预算时truncated=true。

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


## 从命中读取准确媒体字节

状态：固定三图真实字节、绑定/路径拒绝及真实取消/超时/管道关闭已通过非作者验收。
可信单用户、同一Parquet/config；媒体字节读取不提供图像识别或远程读取。

现prepare新增显式`--media-evidence`，与`--sample three`组合仍仅三图15条caption。
默认不加该flag时原单图/三图输入bytes及操作保持；新模式在Parquet中增加media_version/int8=1、
media_bytes/int8及media_sha256/text。每条caption的image_id/image_path与这三个字段一起由config.sha256绑定；
同一image_id的描述必须一致。最多3个asset、200行，ID为正的至多12位整数，定位严格为images/12位ID.jpg。
source.json只记离线来源，不是Rust另取latest的权威。新模式按已固定JPEG SHA校验bytes，沿用前包解码结论，
本次不重新解码；其它默认模式原实际解码保持。旧无v1列的Parquet可继续query，media明确unsupported_media_contract。

```sh
COCO_SOURCE_ROOT=/Users/chad/dev/guradb-data/public-multimodal-20261025
GURADB_EVIDENCE_DIR=artifacts/coco-evidence
.venv/bin/python scripts/prepare_coco_caption.py --annotations-zip "$COCO_SOURCE_ROOT/archives/annotations_trainval2017.zip" --images-zip "$COCO_SOURCE_ROOT/archives/val2017.zip" --output-dir "$GURADB_EVIDENCE_DIR" --sample three --media-evidence
docker run --rm --network none --memory 512m --pids-limit 128 -v "$PWD:/workspace:ro" -w /workspace guradb-rust:1.90.0 /workspace/target/debug/guradb query --config "/workspace/$GURADB_EVIDENCE_DIR/config.json" --sql "SELECT DISTINCT image_id,image_path FROM records WHERE caption LIKE '%kitchen%' ORDER BY image_id"
```

该查询仍唯一397133及images/000000397133.jpg。下面仅用Python作客户端：先收完整Rust查询结果，
把该命中的source_sha256与ID原样交给media，检查两个进程exit0及完整JSON，只打印身份/字节数，避免终端展开整段hex。

```sh
.venv/bin/python - "$GURADB_EVIDENCE_DIR" <<'PYCLIENT'
import hashlib, json, pathlib, subprocess, sys
root = pathlib.Path.cwd()
config = "/workspace/" + sys.argv[1] + "/config.json"
cli = ["docker", "run", "--rm", "--network", "none", "--memory", "512m", "--pids-limit", "128",
       "-v", str(root) + ":/workspace:ro", "-w", "/workspace", "guradb-rust:1.90.0", "/workspace/target/debug/guradb"]
def call(*args):
    completed = subprocess.run(cli + list(args), check=True, capture_output=True)
    return json.loads(completed.stdout)
hit = call("query", "--config", config, "--sql", "SELECT DISTINCT image_id,image_path FROM records WHERE caption LIKE '%kitchen%' ORDER BY image_id")
assert hit["rows"] == [["397133", "images/000000397133.jpg"]] and not hit["truncated"]
evidence = call("media", "--config", config, "--asset-id", hit["rows"][0][0], "--source-sha256", hit["source_sha256"])
raw = bytes.fromhex(evidence.pop("bytes_hex"))
assert evidence["source_sha256"] == hit["source_sha256"] and evidence["asset_id"] == "397133"
assert evidence["image_path"] == hit["rows"][0][1] and evidence["encoding"] == "hex" and evidence["media_version"] == 1
assert evidence["media_bytes"] == len(raw) == 200576
assert hashlib.sha256(raw).hexdigest() == evidence["media_sha256"] == "09e1d25c75f7879bdaa69c327fece5cabacd53939c8c2ef9e87f1c97a2e478c4"
print(json.dumps(evidence, ensure_ascii=False))
PYCLIENT
```

media要求asset ID和命中source SHA；source SHA与config/实际Parquet不符、错ID、NULL/冲突绑定、
未知media_version、非法/越根定位、目录或媒体symlink、缺文件、替换/大小或摘要变化、超限均失败。
安全目录FD下仅打开images/该ID.jpg，不跟随images或JPEG链接；原媒体只读。
成功JSON含media_version=1、asset_id十进制字符串、source_sha256、image_path、media_sha256、media_bytes、encoding=hex、bytes_hex。
397133必须200576B、媒体SHA09e1d25c75f7879bdaa69c327fece5cabacd53939c8c2ef9e87f1c97a2e478c4；
hex解码得到与原ZIP精确成员逐字节相同JPEG。252219/403385同三图原身份不变。
读取的是初次已验证媒体bytes；发布前再核Parquet SHA，不承诺监视两次校验间修改又恢复的文件事件。
不在线解码像素或认证版权；原caption CC BY4与逐图CC BY2来源/摄影者UNKNOWN仍分开保留。

媒体单次读取上界512KiB，每次一个asset；原配置16KiB、Parquet32MiB/解码64MiB、JSON输出2MiB及默认5s/硬10s保持。
JSON hex增加大小但不增加输出预算。身份校验完成前不发布成功输出；完整JSON+exit0才成功。
CLI只写stdout/stderr，不创建或覆盖用户文件、临时文件或后台任务；`--output`及其它未知参数拒绝，已有文件不变。
输出阻塞/关闭、超时或SIGINT可能留下部分stdout，消费者须丢弃；退出124/130或其它非0后内存/FD/线程回收、可重跑。
shell重定向自行写文件不在CLI的文件写入合同内，保留原文件时不要使用覆盖重定向。
完成可删本次派生目录，原ZIP/媒体保持只读；无目录管理、权限/pin/lease、网络/模型或规模能力。


## 可换本地语料的BM25排名

状态：两个不同受支持输入、独立BM25数值真值、准备/查询边界及真实取消恢复已通过非作者验收。
Python仅离线准备，排名在Rust search运行时计算。
输入JSONL每个非空行一个对象，精确字段doc_id/text；doc_id为1–64 ASCII字母/数字/._-且唯一。
text是可打印ASCII英文及空格/tab/CR/LF，1..8192B且至少一个词；不宣称中文/Unicode分词。
可选图文输入必须每行同时加image_id/image_file，不能混有图和无图行；image_file为相对JSONL目录的根内普通本地文件，
拒绝绝对/..及symlink，要求.jpg/.jpeg扩展名及JPEG SOI签名；不解码或认证编码合法性。相同image_id必须对应同一source path/bytes，最多3图、每图512KiB，不下载或解码。
每行是一个排名文档；同图不同caption用不同doc_id，各自计DF/长度，不隐式按图片合并。重复原文可有不同ID。

公开prepare_text_corpus.py --input <JSONL> --output-dir <new artifacts dir>接受这些用户数据，
无COCO/ZIP/preset前置。输出doc_id/text/text_version=1三列；图文追加原media-v1五列。
源上界1MiB JSONL、1..200文档、总text256KiB、输出Parquet1MiB，已有输出/坏格式/未知字段/重复ID等拒绝且失败清新产物。
config自动填真实Parquet SHA；source.json记录输入/媒体捕获摘要和归属责任，不作在线权威。用户须自持素材授权，
准备不认证版权；本包已有COCO图片/原文的来源与UNKNOWN沿用前节，不新增媒体。

英文分析器ascii-alnum-lower-v1：按[A-Za-z0-9]+取连续词、ASCII小写，标点/连字符/撇号分隔；保留数字和stopword，无stem。
每词≤64B，每文档≤2048词、全语料≤65536词；query≤256B、1..8词，重复query词去重并按词排序计算。
空白/只有标点/非ASCII/超限query拒绝；TopK默认10，显式--top-k只允许1..20，无命中空hits。
text_version必须1、ID/text非NULL且类型精确，搜索只接受上述三列或加完整media-v1五列的布局；旧query/media保持，
无text-v1布局或未知版本search拒绝，图文绑定错误沿用media拒绝，不把未知字段解析后忽略。

N/df/dl/avgdl全部来自同一份固定Parquet的全部文档；每文档一条统计，df为包含该词的文档数，dl为分析后词数，avgdl=总词/N。
固定k1=1.2、b=0.75：idf(t)=ln(1+(N-df(t)+0.5)/(df(t)+0.5))；
score(d,q)=sum_t idf(t)*tf(t,d)*(k1+1)/(tf(t,d)+k1*(1-b+b*dl/avgdl))。
query去重词无额外qtf权重。任一分析词tf>0即匹配，累加各词贡献；query不提供AND/短语/前缀等运算语法，字符OR也作为普通词。
分数降序，仅实际f64完全相等再doc_id ASCII字节升序后取TopK，truncated表示还有匹配未返回。
IEEE754 f64不先舍入，数值验收abs/relative各1e-12（差≤1e-12+1e-12*abs(expected)），排序用实际f64总序；
实际f64完全相等时才按ID同分序；相同TF/dl/统计输入保证同分。数学等价的不同逐项和可能有末位差异，
按其实际f64顺序，不用数值容差把不同实际分数强并同分。
返回source_sha256、算法/参数/分析词、N/total_tokens/avgdl/各词df与idf，hits含原文/doc_id/score/dl/各词tf贡献。
图文hit还含media-v1的asset ID/path/SHA/size，用同一source_sha256交原media命令取得准确bytes；text-only hit media=null。
排名时不读取JPEG，媒体命令完整成功才证明实际bytes；缺失/替换或跨source仍拒绝。

```sh
.venv/bin/python - <<'PYTEXT'
from pathlib import Path
import json
p=Path('artifacts/my-text-input'); p.mkdir(parents=True, exist_ok=False)
rows=[{'doc_id':'a','text':'red fox'}, {'doc_id':'b','text':'fox fox fox'}, {'doc_id':'c','text':'blue whale'}]
(p/'documents.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
PYTEXT
.venv/bin/python scripts/prepare_text_corpus.py --input artifacts/my-text-input/documents.jsonl --output-dir artifacts/my-text-ready
docker run --rm --network none --memory 512m --pids-limit 128 -v "$PWD:/workspace:ro" -w /workspace guradb-rust:1.90.0 /workspace/target/debug/guradb search --config /workspace/artifacts/my-text-ready/config.json --query FOX --top-k 2
```

本例hits必须b、a，原文分别fox fox fox、red fox；换blue命中c，无需改引擎或准备关键词Bool。
用户可换JSONL内容/未硬编码query后准备到新输出目录，旧固定输入仍保持原身份；原输入目录/素材只读。
图文行示例为{"doc_id":"caption-1","text":"A local kitchen.","image_id":397133,"image_file":"photos/kitchen.jpg"}；
用户提供该路径的实际本地JPEG，准备复制捕获bytes到images/12位ID.jpg，自动摘要并写同Parquet，不引用另一份latest。
此手写文本示例仅演示输入/算法，不宣称业务相关性优势；独立算法truth与小型人工query/标签观察分别留证。

原32MiB源/64MiB解码/2MiB输出/配置16KiB/默认5s硬10s保持；分词流式只计≤8query词TF，
额外工作集由200文档/256KiB原文/65536词及TopK20硬界约束，无持久索引/无spill，不把DataFusion池冒称整个进程RSS。
source初读与发布前SHA核验一致，完整JSON+exit0；真实取消/期限/管道失败清进程，无用户文件写入或后台任务。
完整性能/覆盖/长稳/发行与业务相关性、跨引擎逐位分数兼容未认证，Actions/部署暂停。


## 外部固定特征的精确向量与RRF数值首包

状态：数值组件、公开外部特征接口、严格拒绝/真实退出恢复及同源媒体关联已通过非作者验收；
真实模型/语义相关性或完整M1.3仍未认证。
复用上节text-v1/可选media-v1语料，DocID全集唯一且固定SHA。外部特征是调用者提供的JSONL，
首行header：format_version=1、source_sha256、documents（须等于语料N）及space；后每非空行只含doc_id/vector。
必须恰好覆盖全部DocID一次，缺失/重复/未知Doc拒绝，不静默漏候选。特征内容不要求来源于COCO/preset。
CLI必须给整个feature文件预先固定SHA256，不另取latest；执行初读及发布前复核同SHA。

space精确字段：id（1..64 ASCII字母数字._-）、dimensions（1..1024）、dtype="f64"、metric="cosine"、
normalization="l2-scaled-f64-v1"、origin（numerical-fixture或external-declared）、model_id/model_revision/
preprocessing_id/license（各非空≤256 UTF8 bytes、无控制字符）。这些是调用者空间/来源声明，不是模型认证。
query JSON精确为format_version=1、source_sha256、同一完整space对象、vector；全部空间字段结构值须相同。
未知字段/版本/错source/错模型空间/类型/维数/非有限数、全部零（含负零）向量拒绝；JSON数字以f64读取，不接受字符串/Bool。

归一先除自身max(abs(component))，再除sqrt(sum(scaled_i²))，顺序均按维索引；可稳定处理有限极大/极小非零值。
向量score为归一后逐项乘积f64顺序求和、clamp[-1,1]的cosine，零相似度规范为+0，更大更近（负相似度仍保留）。
对全N文档算分，按实际f64 score降序/完全相等DocID ASCII升序，最终TopK显式1..20，truncated表示还有文档。
数学truth接受误差仍1e-12+1e-12*abs(expected)，不以容差合并排序，不声明跨CPU逐位或模型相关性兼容。

```sh
# cfg来自上节公开准备的任意text-v1语料；下面是数值操作语法，两个文件由用户提供
# FEATURE_SHA必须是自己features.jsonl的固定真实摘要，不填占位
# paths相对CLI工作目录，或显式本地绝对路径
guradb vector --config cfg.json --features features.jsonl --features-sha256 "$FEATURE_SHA" --query query.json --top-k 10
guradb hybrid --config cfg.json --features features.jsonl --features-sha256 "$FEATURE_SHA" --query query.json --top-k 10 --text-query 'fox'
```

hybrid仍只使用固定ASCII BM25合同。融合固定RRF k=60，按每源已经稳定排好序的1起ordinal位置，
score=（BM25存在时1/(60+bm25_rank)，否则0）+1/(60+vector_rank)，不直接加原始BM25/cosine。
BM25全部正分文档及向量全部N文档参与，任何源不提前TopK；候选union=全N，最后才取TopK。
同源同分也先按DocID给唯一ordinal位置；融合实际f64完全同分再DocID。文本无命中时BM25空、贡献0；
向量源必须完整非空，坏特征不降级忽略。空/非法text-query沿原search拒绝，不把空字符串当另一运算。
输出源SHA、feature SHA、query捕获SHA、space/模型声明未认证、文档数/维数/算法与原文/DocID/同source媒体身份。
融合hit另含每源raw score/rank/RRF贡献和最终score，便于核对；media请求仍用同source SHA+asset ID取得准确bytes。

特征文件≤8MiB、header≤16KiB、单row≤64KiB且总row=N≤200；query文件≤64KiB。
流式逐行解码后立即核维数/身份再保留≤200×1024个f64，额外原特征bytes最多8MiB与≤约2MiB数值数组，
不双份同时解码Parq；原源32MiB/解码64MiB/输出2MiB/默认5s硬10s/no spill与原3JPEG512KiB界不变。
特征初读与终核至多16MiB、query至多64KiB附加读取；读的是已验捕获参数，query捕获SHA用于追溯，不监视其后文件事件。
CLI只写stdout/stderr，完整JSON+exit0；超时/SIGINT/管道关闭可能部分stdout须丢弃，退出后无文件/后台资源，可重跑。

公开完整数值示例使用调用者自行提供的两个特征空间/文件，origin明确numerical-fixture，无模型输出或语义声称。
本首包未提供同source绑定的真实外部模型特征，记录NOT_PROVIDED及具体来源/资源方案；未下载权重或新媒体，不把手工向量当模型有效性。
几何/融合truth、人工标签与真实模型有效性分别留证。原query/search/media入口兼容，本首包不交付ANN/推理/持久索引/目录权限平台。


完整可执行数值示例（在仓库根先按README构建当前binary；目录须全新）：

```sh
GURADB_VECTOR_DIR=artifacts/my-vector-example
.venv/bin/python - "$GURADB_VECTOR_DIR" <<'PYVECTOR'
import hashlib, json, pathlib, subprocess, sys
root=pathlib.Path.cwd(); base=pathlib.Path(sys.argv[1])
assert not base.is_absolute() and (root/base).resolve().is_relative_to(root/'artifacts')
base.mkdir(parents=True,exist_ok=False)
docs=[{'doc_id':'a','text':'red fox'},{'doc_id':'b','text':'fox fox fox'},{'doc_id':'c','text':'blue whale'}]
(base/'documents.jsonl').write_text(''.join(json.dumps(d)+'\n' for d in docs))
subprocess.run([sys.executable,'scripts/prepare_text_corpus.py','--input',str(base/'documents.jsonl'),'--output-dir',(base/'ready').as_posix()],check=True)
source_sha=json.loads((base/'ready/config.json').read_text())['sha256']
cli=['docker','run','--rm','--network','none','--memory','512m','--pids-limit','128','-v',str(root)+':/workspace:ro','-w','/workspace','guradb-rust:1.90.0','/workspace/target/debug/guradb']
for name,dim,values,query in [('two',2,[[1,0],[0,1],[-1,0]],[1,0]),('three',3,[[1,0,0],[1,1,0],[0,0,1]],[1,1,0])]:
    space={'id':'math-'+name,'dimensions':dim,'dtype':'f64','metric':'cosine','normalization':'l2-scaled-f64-v1','origin':'numerical-fixture','model_id':'none','model_revision':'none','preprocessing_id':'self-authored coordinates','license':'self-authored'}
    header={'format_version':1,'source_sha256':source_sha,'documents':len(docs),'space':space}
    features=base/(name+'.jsonl'); features.write_text(''.join(json.dumps(x)+'\n' for x in [header]+[{'doc_id':d['doc_id'],'vector':v} for d,v in zip(docs,values)]))
    request=base/(name+'-query.json'); request.write_text(json.dumps({'format_version':1,'source_sha256':source_sha,'space':space,'vector':query}))
    pin=hashlib.sha256(features.read_bytes()).hexdigest()
    args=['--config','/workspace/'+(base/'ready/config.json').as_posix(),'--features','/workspace/'+features.as_posix(),'--features-sha256',pin,'--query','/workspace/'+request.as_posix(),'--top-k','3']
    for mode,extra in [('vector',[]),('hybrid',['--text-query','fox'])]:
        completed=subprocess.run(cli+[mode]+args+extra,check=True,capture_output=True)
        result=json.loads(completed.stdout)
        assert result['source_sha256']==source_sha and result['features_sha256']==pin
        assert result['model_effectiveness'].startswith('NOT_VERIFIED')
        print(json.dumps({'space':name,'mode':mode,'ids':[h['doc_id'] for h in result['hits']],'scores':[h['score'] for h in result['hits']],'model':'numerical-fixture only'}))
PYVECTOR
```

two空间vector/hybrid均a、b、c（vector为1/0/-1，hybrid前两项同RRF分后按ID）；
three空间vector/hybrid均b、a、c。更换用户features/query内容及完整space，Rust实际重新算分；这两个样本是几何数值而非模型语义结果。
CLI从不把origin/model声明变成已认证权重来源；真实模型有效性仍NOT_VERIFIED。
