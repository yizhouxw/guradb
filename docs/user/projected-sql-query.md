# 固定HTTP Parquet的完整源SQL查询（受限实现）

场景：同一固定本机HTTP Parquet，SQL只取必要列、涵盖完整受支持源的全部行组，经共享Rust SQL/DataFusion执行投影、WHERE和已有typed值参数。新显式`parquet-query`；旧`parquet-read`继续表达物理选择的子集，二者不是同一种关系输入。

## 白名单与输入

新`parquet-query --source sql-source.json --sql '<SELECT>' [--params-json '<原v1typed values>']`。source严格version1、origin、object_key、etag、object_bytes、source_sha256_provenance、header、footer、chunks共9字段，沿原物理descriptor的完整header/footer/所有row_group×column的offset/length/SHA；**不接受columns/row_groups或任何选择字段**，未知/旧物理request直接拒，不忽略选择域。JSON<=16KiB、SQL<=16KiB、参数<=16KiB/最多16、全部输入与argv合并<=64KiB。文件nonlink regular/O_NONBLOCK有界；同127.0.0.1:1024..65535/安全key/强ETag/32MiB对象。

全源1..200行在WHERE/LIMIT前，1..4非空group、1..8平面nullable text/int8/bool。仅原UNCOMPRESSED/noDict/实际PLAIN DataPageV1/V2/RLE levels与所有原footer/crypto/type/实际page/稀疏洞拒绝。SQL复用原共有AST、typed参数及执行器：基础列投影/可用投影alias、WHERE现有布尔/比较/LIKE/IS NULL组合、源列ORDER BY及原NULL排序、非负literal LIMIT。ORDER只按原共享源列规则，不能偷偷把output alias当新来源；聚合/GROUP BY、DISTINCT、JOIN/子查询/表达式投影/动态标识符或其它未开放节点明确拒，不自动继承原query所有SQL节点。参数不拼SQL，$1..$16仅原WHERE literal位置、三标量/typed NULL、缺/多/空洞/类型错/非canonical int8拒。

## 完整关系与实际计划

先真实GET head4/footer，校固定version/metadata全集/全源行数，构造完整schema上的共用Prepared；从**已验证编译表达式**发现投影、WHERE、ORDER全部源列依赖（alias内取原列），排序去重，再读取这些列在**所有**源group的chunk。共享DataFusion MemTable按全源求值，不能把两组子集当整表，不做统计行组裁剪/预抄答案。未投影但WHERE/ORDER引用的列仍必读。LIMIT0/无命中也不跳过身份、完整元数据、全部源行数、计划/必要chunk与编码验证。

请求`2+group_count*required_column_count<=8`，累计body512KiB含元数据，片段和计划在chunk GET前拒；例如3组/2列=8GET，3组/3列=11在2个metadata请求后拒，不偷漏第3列/末组，不退为全文件/全列。返回标准columns/rows/truncated及独立source provenance、源总行数、必要列/全部组/实际read_ranges/GET/body/header计数，source SHA明确只是离线provenance；**selected_ranges_only，unread_content_verified=false**，不把整SHA复述成运行认证。

整个Rust操作绝对10s涵盖输入/HTTP/预检/SQL/输出/取消；最多8GET/body512KiB/单head16KiB64字段/累计head64KiB，remaining在读前限；不HEAD/retry/redirect。Arrow/footer/page/二次解析同64MiB保守工作集模型、DataFusion池32MiB/nospill、进程512MiB4CPU/输出2MiB，不每阶段重置预算。模型不是精确malloc/RSS。ETag信任本机固定后端，未读page不认证；旧源hash、坏源LIMIT0/所有旧命令仍原完整源合同。

## 准备与公开运行

已有COCO15行元数据源`artifacts/clip-real-model-demo/corpus/records.parquet`时（annotation归属/许可沿原来源，图片许可不推断），离线新输出：

```sh
.venv/bin/python scripts/prepare_projected_parquet.py --input artifacts/clip-real-model-demo/corpus/records.parquet --out artifacts/projected-sql-example --sql-source
```

`--sql-source`与显式旧--columns/--row-groups互斥，旧helper默认4file物理请求与摘要保持；新模式data.parquet/sql-source.json/SOURCE.json/local_http_fixture.py四文件，无SQL预计算/离线答案，不扩大导入。完整输入读取/Arrow/规范化写入/整摘要准备成本独立记录，调用者保存可信source descriptor；无覆盖输出/缺源/父link/..拒。

新第13安装物和Root小bundle的公开消费（当次安装物按相邻原receipt校验）：系统Python3.9+、已有固定09bc Docker LinuxARM，无开发checkout/target/mainvenv/PyArrow消费依赖。prefix需全新，使用相邻原stdout sidecar取得checksum；无新镜像/新网络前置。

```sh
(
set -eu
SHA=$(/usr/bin/python3 -c 'import json; print(json.load(open("artifacts/guradb-projected-sql-preview-macos-arm64-docker-linux-arm64.pyz.json"))["sha256"])')
/usr/bin/python3 artifacts/guradb-projected-sql-preview-macos-arm64-docker-linux-arm64.pyz install --sha256 "$SHA" --prefix /tmp/guradb-projected-sql-preview
export GURADB_DOCKER_HOST=unix:///var/run/docker.sock
export GURADB_DOCKER="$(command -v docker)"
DATA="$PWD/artifacts/projected-sql-demo"
RUNTIME=sha256:09bc0a87408c56bd4fe912df3ba3d499ea2279ea32cdeddf051a7a3dd3ddb52f
SERVER=$("$GURADB_DOCKER" --host "$GURADB_DOCKER_HOST" run -d --rm --pull never --network none --read-only --memory 128m --cpus 1 --pids-limit 64 --label guradb.local-http-fixture=v1 -v "$DATA:/fixture:ro" --entrypoint python3 "$RUNTIME" /fixture/local_http_fixture.py --object /fixture/data.parquet --key caption/v1/records.parquet --etag '"caption15-fixed-v1"' --port 38081)
trap '"$GURADB_DOCKER" --host "$GURADB_DOCKER_HOST" rm -f "$SERVER" >/dev/null 2>&1 || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
/usr/bin/python3 - "$SERVER" "$GURADB_DOCKER_HOST" "$GURADB_DOCKER" <<'PYREADY'
import json, subprocess, sys, time
stop = time.monotonic() + 5
while time.monotonic() < stop:
    p = subprocess.run([sys.argv[3], '--host', sys.argv[2], 'logs', sys.argv[1]], capture_output=True, timeout=min(1, max(.001, stop-time.monotonic())))
    if any(json.loads(line).get('event') == 'ready' for line in p.stdout.decode().splitlines() if line.strip()):
        break
    time.sleep(min(.02, max(0, stop-time.monotonic())))
else:
    raise RuntimeError('fixture did not become ready')
PYREADY
/tmp/guradb-projected-sql-preview/bin/guradb --data-root "$DATA" --local-http-container "$SERVER" parquet-query --source /data/sql-source.json --sql 'SELECT doc_id, text_version FROM records WHERE text_version = $1 ORDER BY doc_id LIMIT 2' --params-json '{"version":1,"values":[{"type":"int8","value":"1"}]}'
"$GURADB_DOCKER" --host "$GURADB_DOCKER_HOST" logs "$SERVER"
)
```

独立全源SQLite先冻预期rows严格为`[["c-107395","1"],["c-109132","1"]]`，columns为doc_id/text、text_version/int8，truncated=false；全15行关系/全部3组，每组2列，实际应8GET/3829payload（head4/footer3165+3×111/109B），decoded_rows=source_rows=15，不是只读10行后得相同头两行。可把WHERE换`text LIKE $1`且只SELECT doc_id，参数text"%kitchen%"；所需doc_id+text两列，完整源中间组5条c-370509/370584/372252/372765/375891都必须返回，不能沿旧[0,2]组漏读。WHERE/ORDER引入第三独立列则3组×3列需要11GET，在两metadata后/任何chunk前resource_limit，不以LIMIT0或无命中放宽。

SOURCE.json记录原全读准备3986B/15行Arrow、规范化8292B完整摘要与所有片段mapping；sql-source.json严格无物理选择。caption归属COCO Consortium/annotation CC BY4.0，原annotations member摘要afe3b30e…沿原独立出处；图片许可不由caption推断，本例不读/解码/下载图片。候选支持边界、精确M与安装物分别由独立证据绑定；本页期望不能替代当次运行检查。

## 验收与恢复

独立先全读原source并用独立SQL冻结全表结果、必要列集合与NULL/重复/参数边界；实测常量/参数WHERE、空结果、ORDER不在SELECT、alias/不支持节点、全200/201、3×3预算拒、LIMIT0坏metadata/必要chunk、实际多GETdeadline/取消/满输出与恢复，以及旧独立1GET/物理parquet-read/完整源query/同prefix MCP3。小必要raw wire预留范围与其它redacted/error/source/SQL oracle分开，私有payload/fixtures回收不能写成全量持久。只core-limited；一般SQL下推/任意Parquet/远端湖S3/TLS/新MCP工具、规模/发行未授。失败命令不发布结果/不写源，读取消进程退出后fresh重试同固定版本，不存在后台监听器。

本首片已由独立全源SQLite真值核对：32查询真值、隐藏WHERE/ORDER依赖与别名遮蔽、完整中组厨房五行/typedNULL与参数边界、原200源行/201及LIMIT0拒例、11GET计划在两metadata后拒、未选大列跳读和实际超时/取消/输出恢复。范围只覆盖本文白名单；原观察器共享dict污染导致的4次差异已保，修复观察器后只补受影响条目，不充产品失败或PASS。精确commit/包与退出终态另记，不授完整SQL/资源全期认证。
