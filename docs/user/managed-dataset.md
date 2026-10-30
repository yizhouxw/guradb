# 单机托管完整批导入（本机受限候选已验）

目标为可信单用户、一个新本地root/一个dataset，Rust CLI将已支持图文Parquet及可选固定features完整复制为owned revision。不是目录别名或Python串命令。现有directconfig/view格式保持，旧root不隐式升级；新managed catalog仅在显式新root创建，旧binary拒绝新格式。

受限入口：`guradb dataset import --store ROOT --name NAME --operation-id ID --config FILE [--features FILE --features-sha256 SHA]`；`dataset status|reconcile|retry --store ROOT [--operation-id ID]`。输入白名单沿现generic图文字段/三标量Int64/Boolean/Utf8、最多32列/200Doc/3JPEG；列名、顺序、类型、nullable共同确定schema SHA，替换必须完全同schema/feature模式/typed space，不做schema演化。拒绝重复Doc、坏行/缺媒体/错source/features，不丢行。首片至少真实15→4两完整版本。

dataset ID生成一次并落盘，不依赖物理rowid/path；revision包含dataset/schema/source/feature完整身份、generation和固定view ID。公开operation记录完整输入指纹与capturing/ready/committed/failed状态；所有owned source/JPEG/features校验、fsync后才ready，catalog一次原子替换同时发布revision/current与operation提交事实。原始输入在commit后可移除，owned旧版本和固定成员仍可读。每次公开读用返回固定view ID走原Rust view六入口；MCP仍三只读工具，不增加写工具，不暗改旧root current。

最多2个distinct revision/view、8个持久operation、单inflight/kernel flock，128MiB owned data含stage/1MiB描述且catalog16KiB，newowned≤1GiB。源32/decode64/features8/output2MiB/N200/dim1..1024/TopK20与Rust512MiB/4CPU/每operation10s不扩大。已有current之外的临时对象占同一2slot与128MiB预算；无GC/pin/并行后台/append/CDC/UPDATE/DELETE/MERGE/多租户或分布式fence。

同operation ID同输入重放返回原结果且不改变新current；同ID异指纹拒绝。指纹绑定声明source SHA/feature SHA/name，媒体/Doc/schema由source完整bytes覆盖；提交结果未知先status，再无输入的retry/reconcile对账。所有输入校验前的拒绝不称已创建operation；持久admission后中断可见capturing。若完整owned对象已落盘，可公开reconcile验证后继续ready/commit；若仅partial stage则清本op暂存并标failed，不能假成功，重试须新operation ID和完整输入。旧committed operation retry永不倒退新revision，commit复核parent current/generation；单inflight并非通用异步双fence。坏catalog/未知文件或不可证明归属拒绝，不手改JSON救恢复。

用户先按既有说明准备输入；新包不下载、运行encoder或读raw ZIP。许可与原源归属保持，caption许可不覆盖照片。保护现有三安装物/09bc引用/SDK与旧6资源，新的binary/包独立具名不覆盖旧63fd。真实中断关键持久相位、提交未知、原源移除后的owned读取、拒绝/旧op重放/并行拒绝由非作者实测后才标支持。当前仅本机受限候选通过，不构成M2/完整数据管理平台完成，精确M新安装物随本包单独给出。

首次admission前catalog.tmp只为已知有界原子写暂存，公开reconcile可清理尚未admitted的已知空root而不猜非空objects。pending描述也经同一受锁temp原子rename，避免partial journal伪事实；未知文件/非空objects缺catalog拒绝。schema/input/revision精确内容格式见ADR0040。

导入在admission前预留完整ready与committed描述，三态均≤16KiB；超限整批拒绝且无新operation/owned暂存，不以增大catalog预算或丢历史换成功。

## 可复制操作

新包独立命名`guradb-managed-preview-macos-arm64-docker-linux-arm64.pyz`，配套同名`.json`发布回执包含确切SHA/源码commit/逐源指纹，不覆盖旧63fd包。先核回执来自本次交付，再按摘要安装到fresh prefix；缺本地09bc runtime时doctor明确拒绝，不自动下载。

```sh
RELEASE=/Users/chad/dev/guradb/artifacts/guradb-managed-preview-macos-arm64-docker-linux-arm64.json
PACKAGE=/Users/chad/dev/guradb/artifacts/guradb-managed-preview-macos-arm64-docker-linux-arm64.pyz
PREFIX=/tmp/guradb-managed-preview
SHA=$(/usr/bin/python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["sha256"])' "$RELEASE")
/usr/bin/python3 "$PACKAGE" install --sha256 "$SHA" --prefix "$PREFIX"
"$PREFIX/bin/guradb" doctor
```

以下显式使用本机已经验证的既有小输入根，不下载或执行encoder，root内保留三份既有bundle。其他输入准备见[alpha手册](simple-alpha.md)的generic图文/feature合同。`managed-demo`必须不存在，不能先mkdir这个store（只需DATA父目录存在）；显式恢复已有空壳用dataset reconcile，未知非空root不猜空库。CLI安装仅需要系统Python与已有local Docker，不挂开发checkout/target/主venv。

```sh
DATA=/Users/chad/dev/guradb/artifacts
GURADB="$PREFIX/bin/guradb"
"$GURADB" --data-root "$DATA" dataset import --store /data/managed-demo --name demo --operation-id A --config /data/clip-real-model-demo/corpus/config.json --features /data/clip-real-model-demo/features/features.jsonl --features-sha256 8e0ad19f7f3530755ff357f5d01622d8c9893d54ea251fdf8550d055911d15bb > /tmp/managed-A.json
VIEW_A=$(/usr/bin/python3 -c 'import json;print(json.load(open("/tmp/managed-A.json"))["current_view"])')
"$GURADB" --data-root "$DATA" dataset import --store /data/managed-demo --name demo --operation-id B --config /data/local-view-refresh-demo/store/objects/d873f8762428a2d16833f8a0cf75277b500e9d2e6962d4370857491f484f0b0b/config.json --features /data/view-vector-sample-demo/store/objects/e66da92791daaa49dbe4a892fe2f586b2a7b3ce52f73bfe4d82bed4a49cdc04d/features.jsonl --features-sha256 216ad54594e1fe71d1e0c61a2ea020af56b41688d180f0111e8fde4e492033ef
"$GURADB" --data-root "$DATA" dataset status --store /data/managed-demo --operation-id B
"$GURADB" --data-root "$DATA" dataset retry --store /data/managed-demo --operation-id A
"$GURADB" --data-root "$DATA" view query --store /data/managed-demo --view "$VIEW_A" --sql 'SELECT doc_id,text FROM records ORDER BY doc_id'
"$GURADB" --data-root "$DATA" view query --store /data/managed-demo --view current --sql 'SELECT doc_id,text FROM records ORDER BY doc_id'
```

预期A/B同dataset与schema，revision generation1→2，source分别8eaaa37c…/d873f876…；旧A15/currentB4，重放A只返回旧operation而current仍B。用返回的具体view ID调用原media/sample可固定旧版本；输入目录不再是owned revision的读取依赖，自己创建的外部输入副本可移除。不要删除本机共享原bundle/模型/原ZIP或其它用户数据。每份revision仍需保留完整managed store，丢owned文件明确失败；没有备份/GC平台承诺。

进程中断/结果未知时先`dataset status --store ... --operation-id ID`，再`dataset retry --store ... --operation-id ID`或`dataset reconcile --store ...`。partial capture会成为failed并清本op暂存；已完整owned ready可commit；同ID失败不暗换新输入，另给新ID重试完整输入。metadata的rows/assets及committed typed-space必须与owned事实/原Record一致，损坏拒绝。未认证断电、fsync硬件故障、恶意并发和完整M2；MCP继续原三只读白名单，不增加dataset写工具，新格式不隐式切换旧root。

本机非作者实际：三次新operation真实KILL（partial capturing/ready/committed返回未知）经public对账收敛，旧成功/失败不倒退current；原源副本物理移除后owned A15/B4、准确媒体与sample保持。9类坏行/依赖/模式拒绝、旧v1/v2与directconfig最小兼容通过。V1损坏catalog rows4→3误报已保FAIL；V2对所有metadata返回核owned计数并对committed完整typed-space/Record绑定，损坏拒绝定向通过，不重KILL。16KiB三态预留与边界单位亦经复核。工具初空壳/virtiofs路径观测失败不计产品通过；不授断电或通用异步fence。
