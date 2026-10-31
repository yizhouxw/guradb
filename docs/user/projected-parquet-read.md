# 固定HTTP Parquet按列/行组读取

状态：实验白名单实现与非作者候选真实验收通过（core-limited）；精确主线/新包另独立绑定。新显式 `parquet-read --request <JSON>` 返回结构化列/记录与实际读范围；旧query/media/Iceberg/managed/view/MCP三工具保持完整源校验和offline，不接通旧SQL远端下推。

输入是可信操作者一次离线完整读取/规范化Parquet并生成的固定描述。准备成本单列：完整源bytes/Arrow行、规范化写入/完整SHA和每片段SHA，可能全读原件；每次消费不再次全读、全源hash或全量Arrow。描述不是签名/权限系统，操作者保留固定对象版本；完整源SHA仅provenance，当前只证明实际所选范围与已取footer、未读内容不认证。

最小格式：单对象1..32MiB，非空1..200源行（在任何选择前检查），1..4非空rowgroups、1..8唯一ASCII命名平面列；可空int64/text/bool。UNCOMPRESSED，禁止dictionary/外部column file/嵌套、repeated、未知类型或codec。DataPageV1/V2均支持，选中实际page值编码仅PLAIN，V1 level编码RLE；页头须用既有Parquet reader检查，不把footer encodings当page版本证明。全schema/codec/行数从已核footer约束，即使未选列不支持也拒；未读chunk页面不声称验证。

request JSON≤16KiB，version=1；固定identity(origin/object_key/etag/object_bytes)继承ADR0047严格127.0.0.1端口/安全key/strong ETag。source_sha256仅离线来源描述；header/footer及每个columnchunk记录offset/length/sha256，descriptor必须与实际footer解出的完整片段集合一致。columns为schema索引自然升序1..3项，row_groups为自然升序1..2项；空/重复/无序/越界拒。输出列按schema顺序，行按group顺序与组内原序；列type为int8/text/bool，int64输出十进制JSON字符串，text字符串、bool布尔、NULL为null。无filter/排序/LIMIT/SQL。

每操作实际GET head4、footer+8byte trailer及选中group×column chunk，不合并/重试/HEAD/重定向；最多8GET、累计payload512KiB、单响应头16KiB/64字段且累计头64KiB，HTTP接收循环使用剩余累计头预算，不是超读后才相加拒。每片段强If-Match、精确CR/CL/ETag与独立SHA，全操作绝对10s包括输入/所有HTTP/页头/Arrow/输出及取消；原独立object-range仍1GET/16KiB头，不能沿组合界放大。

稀疏ChunkReader只提供已取得并验过的片段，洞读/跨未读区域硬错，无补0/文件回退/隐式HTTP。Arrow ProjectionMask及rowgroups只解码所选chunk；metadata/页头先经受限官方Compact协议校验binary/string长度、容器count/深度及保守heap，再用相同不可变bytes交官方Parquet reader，避免按伪造声明先分配；原始类型矛盾、加密声明/未知平面schema拒。metadata/实际页预检/Arrow共用64MiB，Rust512MiB4CPU/输出2MiB，无spill，不建新DataFusion执行器。缺片段/错版本/footer/hash/descriptor/非法encoding/预算/超时取消明确拒并清socket，无有效完整结果；合法相同请求可恢复。

本机预览仅新命令显式 --local-http-container fullID，复用同localUnix Docker/固定09bc/none fixture namespace与两mount；旧入口默认none/错误开关拒。Python只离线准备、标准库工程HTTP fixture与独立真值，不执行在线投影/查询，不下载模型/媒体/软件。

公开入口：`scripts/prepare_projected_parquet.py`（已实现）从既有受支持小Parquet离线规范化为uncompressed/noDict/最多3个非空group，并写data.parquet/request.json/来源成本说明/参考fixture到不存在且父链无链接的新目录，拒覆盖/缺源/最终源链接、输出父链链接及..穿越。输入全读与规范化成本公开，未预存结果。用户安装包只需新第12包+原stdout sidecar+≤4MiB bundle和既有Docker/SystemPython，不依赖开发checkout/target/主venv；离线准备依赖已有PyArrow单列，不冒运行期依赖。具体公开命令如下；非作者候选已真实通过，H-M/fresh身份仍按独立交付链另验。

真实输入使用已有COCO15 caption元数据，图片许可与caption归属沿原记录，未重新读取/解码媒体。工程nullable/200行等fixture独立标记，不作大规模结果。HTTP局部读不证明S3/远端湖/通用Parquet/SQL下推/完整来源当前认证或性能优势。

## 可复制准备与消费者入口

随包小bundle为已有COCO元数据的规范化副本，caption归属COCO Consortium、annotations CC BY4.0（https://creativecommons.org/licenses/by/4.0/），子集/标量投影与Parquet重写；不是图片许可、图片作者或当前照片权利认证。原annotations member captions_val2017.json的摘要afe3b30e…沿已有独立来源记录，本文不读取图片。SOURCE.json分别记原3986B全读/完整15行Arrow、规范化8292B/完整hash与行组写入；完整source SHA仅provenance。

已持有本仓既有原小Parquet时，以下离线入口可生成新bundle；需要已安装PyArrow22的工程环境，仅此准备步骤使用它。没有原件则明确缺源，不能从答案反造输入。out需全新且父链无链接；生成4file，不预存查询结果。

```sh
.venv/bin/python scripts/prepare_projected_parquet.py --input artifacts/clip-real-model-demo/corpus/records.parquet --out artifacts/projected-parquet-demo-new --columns 0,2 --row-groups 0,2
```

消费可直接使用已交付的artifacts/projected-parquet-demo四文件与新第12包/原sidecar；换用自己新准备目录时只替换下面DATA路径。不需要PyArrow/开发venv/checkout/target做消费。以下仅需要系统Python3.9+及已有固定09bc Docker LinuxARM，本机Mac-arm预览条件与前包一致，receipt摘要非发行签名，prefix必须新。

```sh
(
set -eu
SHA=$(/usr/bin/python3 -c 'import json; print(json.load(open("artifacts/guradb-projected-parquet-preview-macos-arm64-docker-linux-arm64.pyz.json"))["sha256"])')
/usr/bin/python3 artifacts/guradb-projected-parquet-preview-macos-arm64-docker-linux-arm64.pyz install --sha256 "$SHA" --prefix /tmp/guradb-projected-parquet-preview
export GURADB_DOCKER_HOST=unix:///var/run/docker.sock
export GURADB_DOCKER="$(command -v docker)"
DATA="$PWD/artifacts/projected-parquet-demo"
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
/tmp/guradb-projected-parquet-preview/bin/guradb --data-root "$DATA" --local-http-container "$SERVER" parquet-read --request /data/request.json
"$GURADB_DOCKER" --host "$GURADB_DOCKER_HOST" logs "$SERVER"
)
```

本例投影columns[0,2]为doc_id/text_version，groups[0,2]取10行，预期rows依次为(c-107395,"1")、(c-109132,"1")、(c-111433,"1")、(c-114199,"1")、(c-114511,"1")、(c-501985,"1")、(c-507367,"1")、(c-508369,"1")、(c-510313,"1")、(c-510664,"1")。source_rows=15/decoded_rows=10，request_count=6/payload_bytes=3609：head4+footer3165+四个111/109/111/109B的selected chunks，未取中间group及其它列chunk。header_bytes是实际收到的头，不是物理网络/整个数据库成本；decode_charged_bytes包含metadata元素保守预留和二次解析的共享记账，不是实测RSS/物理峰；verification=selected_ranges_only、unread_content_verified=false。可修改request的升序columns/groups选择其它已描述范围，仍受同8GET/512KiB/10s，超界拒绝。

此处记录为10:11作者首结果与10:12原source后验字节/descriptor重绑，不倒填成实现前所有规范化bytes已验证；原COCO行真值09:59独立先冻。非作者候选已实证全源200前判/8GET与累计body预算、大未选chunk跳读、14分配负例、64KiB累计头即时拒、真10s/INT/输出关闭与恢复，旧完整源/单Range1GET/MCP3兼容；具体M/包身份和owner终态另核，不作完整故障/发布认证。
