# 固定本机HTTP对象的有界Range字节

状态：受限Rust实现与非作者候选运行验收通过（core-limited）；精确main/预览包身份由本次交付另核。独立Rust object-range命令只核一次固定版本的选中范围，不把未读对象、未消费TCP尾流或用户提供的整对象摘要冒全量认证。旧query/media/Iceberg/managed/view完整源校验与默认offline不变；没有旧SQL下推/S3/任意HTTP/TLS/认证或MCP provider工具，原MCP仍3个。

请求入口`object-range --request <file>`，普通非链接JSON文件≤16KiB，严格version=1/字段白名单。origin只精确http://127.0.0.1:1024..65535（显式十进制端口），无DNS/localhost/其它IP/HTTPS/凭证/代理环境/路径/query/fragment。object_key为非空相对ASCII安全分段（总≤4096bytes/最多16段/每段≤255bytes），发往`/objects/<key>`；拒空段、.、..、百分号、反斜杠、CRLF/?/#及动态headers。etag是短非空强quoted opaque ASCII值（≤128bytes，无weak/escape/list），不是整对象内容认证。object_bytes为1..33554432，offset非负整数、length1..524288且checked offset+length≤object_bytes，range_sha256为预期范围64小写hex。超时固定10s、无调用方扩张字段；错误不回显输入值/secret。

```json
{"version":1,"origin":"http://127.0.0.1:38081","object_key":"sintel/v1/silent.avi","etag":"\"sintel-silent-v1-20261031\"","object_bytes":221902,"offset":4093,"length":257,"range_sha256":"59d9b4390f7495229aac57b81237acac78cdc060f39d459abf1e549efd20ae34"}
```

每操作严格**1 GET**、不HEAD/重试/重定向，发送Range bytes=offset..end、If-Match、Accept-Encoding identity、Connection close。只接HTTP1.1/206；ETag/Content-Range/Content-Length各恰一且精确，关键头含CE/CT/Connection的重复按大小写不敏感拒；Connection只准缺省或close，CT只准缺省或application/octet-stream（值不区分大小写），TE/Trailer/Upgrade/折行/bareLF/歧义/多范围/multipart/压缩/其它编码/1xx/200/3xx/其它状态拒。所有响应头值限可打印ASCII（边缘SP/HTAB可trim）。响应头累计≤16KiB/64头，先完整头校验，再按Content-Length恰读length≤512KiB并核rangeSHA，才输出成功JSON；无socket复用或后台任务，固定10s绝对界贯穿request读取/connect/头/body/hash/stdout，drip不刷新期限。输出仍2MiB、Rust512MiB4CPU，所有旧界不扩。

**范围边界**：按[RFC9112 Content-Length帧](https://www.rfc-editor.org/rfc/rfc9112.html#section-6.3)读满L即关闭，不等EOF、不探测未读tail；正确CL=L与前L正确bytes后另有未消费TCP数据，可以成功认证所选range，不能声称tail已验证或全部长流拒。CL错、前L摘要错、读不足L则拒。强If-Match/ETag按[RFC9110](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.1)做后端版本条件，但后端重用/撒谎ETag不证明未读部分，rangeSHA仍只核选中bytes。

成功返回backend=local-http-range-v1、origin/object_key/etag/declared_object_bytes、offset/length/range_sha256、request_count=1、response_status=206、header_bytes、encoding=hex/bytes_hex及verification=range_only（字段以ADR0047冻结为准）。记录是客户端所消费range/HTTP头计数，与server attempted/write-return日志分列，不作物理网卡/全数据库性能证明。失败无成功payload，之后合法请求可恢复；真实timeout/INT/断连清本操作socket与own容器，不承诺完整故障矩阵。

本机预览需要显式`--data-root <data> --local-http-container <full64hexID> object-range --request /data/request.json`。开关只准这个新命令；launcher在同一现有本机Unix Docker endpoint inspect精确ID/Running/固定09bc image/networknone/无publishedports/工程label后仅`--network container:<ID>`共享fixture的纯loopback namespace，无fallback/global配置。旧命令和MCP带开关拒，未带开关的新命令拒；旧入口仍networknone，不开放外网/host network。fixture容器临时Python标准库工程服务、networknone且只bind127.0.0.1，产品Rust不监听，也不启动/导入Python；工程HTTP fixture由用户单独运行，Rust仅作为HTTP客户端。

用户小bundle`artifacts/local-object-range-demo`（≤4MiB）包含既有真实Sintel静音AVI副本、request.json、版本化参考fixture和来源/许可/range真值。对象221902B/SHA5d3147365cb8e158dc9ad077acb8cbbc373b197cdbb6ee21aacf54ca80f4a149来自上一视频组件；CCBY3.0/© copyright Blender Foundation | durian.blender.org、缩放/静音/降帧等派生历史与原载体UNKNOWN不变，见[视频页](video-evidence.md)。本片只读range，不重新解码/认证整对象。边界pattern仅工程fixture，不冒真实规模。

实际新第11包为artifacts/guradb-local-object-range-preview-macos-arm64-docker-linux-arm64.pyz和相邻原.pyz.json。仍Mac-arm/系统Python3.9+/既有09bc LinuxARM Docker；receipt来自可信交付来源，SHA检查非发行签名，prefix必须全新。只需包与用户bundle、系统Python/既有Docker，不依赖开发checkout/target/主venv或ignored TASK脚本。

```sh
(
set -eu
GURADB_RANGE_SHA=$(/usr/bin/python3 -c 'import json; print(json.load(open("artifacts/guradb-local-object-range-preview-macos-arm64-docker-linux-arm64.pyz.json"))["sha256"])')
/usr/bin/python3 artifacts/guradb-local-object-range-preview-macos-arm64-docker-linux-arm64.pyz install --sha256 "$GURADB_RANGE_SHA" --prefix /tmp/guradb-local-object-range-preview
export GURADB_DOCKER_HOST=unix:///var/run/docker.sock
export GURADB_DOCKER="$(command -v docker)"
GURADB_RANGE_DATA="$PWD/artifacts/local-object-range-demo"
GURADB_RANGE_RUNTIME=sha256:09bc0a87408c56bd4fe912df3ba3d499ea2279ea32cdeddf051a7a3dd3ddb52f
GURADB_RANGE_SERVER=$("$GURADB_DOCKER" --host "$GURADB_DOCKER_HOST" run -d --rm --pull never --network none --read-only --memory 128m --cpus 1 --pids-limit 64 --label guradb.local-http-fixture=v1 -v "$GURADB_RANGE_DATA:/fixture:ro" --entrypoint python3 "$GURADB_RANGE_RUNTIME" /fixture/local_http_fixture.py --object /fixture/object.avi --key sintel/v1/silent.avi --etag '"sintel-silent-v1-20261031"' --port 38081)
trap '"$GURADB_DOCKER" --host "$GURADB_DOCKER_HOST" rm -f "$GURADB_RANGE_SERVER" >/dev/null 2>&1 || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
/usr/bin/python3 - "$GURADB_RANGE_SERVER" "$GURADB_DOCKER_HOST" "$GURADB_DOCKER" <<'PYREADY'
import json, subprocess, sys, time
stop = time.monotonic() + 5
while time.monotonic() < stop:
    p = subprocess.run([sys.argv[3], '--host', sys.argv[2], 'logs', sys.argv[1]], capture_output=True, timeout=min(1, max(.001, stop-time.monotonic())))
    rows = [json.loads(s) for s in p.stdout.decode().splitlines() if s.strip()]
    if any(r.get('event') == 'ready' for r in rows):
        break
    time.sleep(min(.02, max(0, stop-time.monotonic())))
else:
    raise RuntimeError('local fixture did not become ready')
PYREADY
/tmp/guradb-local-object-range-preview/bin/guradb --data-root "$GURADB_RANGE_DATA" --local-http-container "$GURADB_RANGE_SERVER" object-range --request /data/request.json
# 预期offset4093/length257/范围SHA59d9…和准确257 bytes；server日志应恰1 GET/Range/If-Match。
"$GURADB_DOCKER" --host "$GURADB_DOCKER_HOST" logs "$GURADB_RANGE_SERVER"
)
```

上面fixture和launcher都显式使用同一既有本机Unix socket/CLI，不继承远端Docker context；不修改daemon或用户全局配置。上面显式fixture是临时工程前置，参考命令用subshell/trap清自己的server，并只轮询有界ready日志而不额外HTTP探测；并非数据库服务部署。脚本从有界普通文件启动时捕获bytes/版本，保留期间保持同一版本，不能把此信任升为通用provider证明。候选非作者已从原对象核七组range，验证严格协议拒绝、真实10s/INT/闭pipe及恢复，并实际核namespace的1GET/257bytes与旧SDK三工具兼容；安装首跑和精确main仍独立验收。未测一般HTTP兼容/远端湖/规模或物理网卡性能。
