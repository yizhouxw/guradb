# 固定短视频的原字节与帧证据

状态：受限Rust组件与同源CLI/MCP已独立验收；本片精确main安装消费另由最终报告给出，完整M2/发行未认证。本片仅可信单用户、本地固定Parquet、既有Rust CLI与三个MCP工具。文本命中外部描述，不做视频理解、字幕/声音识别或模型检索。

media_version=2的严格9列沿[音频合同](audio-evidence.md)，新增asset_type=video/x-msvideo及videos/12位asset_id.avi。JPEG v1响应和WAV v2保持。跨类型ID仍唯一、最多3资产/200行、每媒体512KiB、输出2MiB、source32MiB、Arrow/decode64MiB/pool32MiB无spill、Rust512MiB/4CPU/10s、RPC64KiB不变。media请求用实际命中返回的source_sha256/asset_id；view取证用该命中具体view_id，MCP media拒current，CLI旧current兼容不变。旧view始终固定旧源与bytes。

首片仅AVI1.0 RIFF/AVI、唯一未压缩24bit BI_RGB/BGR视频，无音轨。BITMAPINFOHEADER40、planes1、宽1..320/高绝对值1..240，支持明确top_down/bottom_up；DWORD行stride及每帧完整像素长度必须吻合。整数fps1..30、scale1、帧1..30，avih微秒值严格floor(1000000/fps)，avih flags必须含HASINDEX0x10且仅可另含ISINTERLEAVED0x100/TRUSTCKTYPE0x800；strh flags为0。avih/strh/movi实际帧/idx1对应一致，精确rate_num/rate_den及duration_num/duration_den表达时长。整文件最多128个RIFF chunk；已知JUNK与INFO只按有界布局跳过，不作其内容语义承诺；其余未知语义、音轨/压缩/AVIX/OpenDML/嵌套rec/截断/溢出/尾垃圾/索引或尺寸时间冲突拒绝。AVI已知最大字节率/建议buffer/quality/像素每米提示不作为分配或新语义承诺。Rust直接验证每个原始像素帧布局，不调用外部decoder、不隐式联网；独立工程FFmpeg实际消费帧，不以文件头代替消费证据。

响应在v2身份和完整bytes_hex外加video对象：container/encoding/width/height/row_order/row_stride/frames/rate_num/rate_den/duration_num/duration_den（字段以冻结ADR为准）。不存在Range/时间切片/在线抽帧或通用MP4兼容。缺失/替换/错类型与关联/SHA/版本/越根/链接/特殊文件/输出超额均失败且无成功payload，下一合法请求须恢复。v2 feature-view/vector/hybrid/sample仍拒绝；普通managed等未验分支保留未验，不一概承诺支持或拒绝。

真实源为[W3C Sintel示例载体](https://media.w3.org/2010/05/sintel/trailer.mp4)，[W3C示例页](https://www.w3.org/2010/05/video/mediaevents.html)关联Sintel。实际4372373B、SHA256 b670602fa00934ca27c4351bb0efe7ea7a07fae57284e44226025eeed7c51254；H264/854x480/24fps/1253帧、约52.208333秒，含AAC。它是公开3D动画，并非本项目生成或实拍；载体先前剪辑/编码史UNKNOWN。[Blender官方Sharing](https://durian.blender.org/sharing/)采用[CC BY3.0](https://creativecommons.org/licenses/by/3.0/)，片段署名“© copyright Blender Foundation | durian.blender.org”。本片只生成无音轨派生，不分发独立配乐/商标或宣称原Blender字节一致。

本机现有FFmpeg4.4工程工具从10..11秒生成5帧/5fps/160x90的silent BGR24 AVI；实际221902B、SHA256 5d3147365cb8e158dc9ad077acb8cbbc373b197cdbb6ee21aacf54ca80f4a149。剪辑、缩放、降帧率及有损派生如实列入source记录，不称原质量/原字节未变或产品提速。FFmpeg/ffprobe仅本机离线工程reader，不复制进Rust安装物；其它工具版本需重新核产物，不能继承本例SHA资格。原MP4为临时准备输入，用户小bundle只保派生、原URI/SHA/参数与署名，不保整段原MP4。既有WAV/JPEG许可与UNKNOWN各沿原合同，不被视频许可覆盖。

复用scripts/prepare_text_corpus.py的v2 JSONL，新增video/x-msvideo和asset_file相对普通AVI文件；离线仅固定有界RIFF/AVI字节与SHA，不代替Rust完整帧/索引验证，不负责下载/转码。下面目录须新建，错误不覆盖旧输入/输出。数据准备需既有工程venv/pyarrow；生产与安装消费者不需它们。

```sh
mkdir artifacts/video-input
# 将上述准确源置于此路径；下载仅离线准备，须先核许可/4372373B与完整SHA。
GURADB_FFMPEG=/Users/chad/.local/bin/ffmpeg
"$GURADB_FFMPEG" -hide_banner -loglevel warning -threads 4 -ss 10 -i artifacts/video-input/sintel-trailer.mp4 -an -t 1 -vf fps=5,scale=160:90 -filter_threads 4 -c:v rawvideo -pix_fmt bgr24 -threads 4 -frames:v 5 -fflags +bitexact -flags:v +bitexact -f avi -n artifacts/video-input/sintel.avi
cp artifacts/audio-evidence-demo/audio/900000000001.wav artifacts/video-input/train.wav
cp artifacts/clip-real-model-demo/corpus/images/000000397133.jpg artifacts/video-input/kitchen.jpg
cat > artifacts/video-input/corpus.jsonl <<'JSONL'
{"doc_id":"sintel-video","text":"Sintel animated film trailer silent video excerpt Blender Foundation","asset_id":900000000002,"asset_type":"video/x-msvideo","asset_file":"sintel.avi"}
{"doc_id":"train-whistle","text":"Steam train whistle Daniel Simion field recording audio","asset_id":900000000001,"asset_type":"audio/wav","asset_file":"train.wav"}
{"doc_id":"coco-kitchen","text":"Existing COCO kitchen photograph image 397133","asset_id":397133,"asset_type":"image/jpeg","asset_file":"kitchen.jpg"}
JSONL
.venv/bin/python scripts/prepare_text_corpus.py --input artifacts/video-input/corpus.jsonl --output-dir artifacts/video-evidence-demo
```

新第10安装物为artifacts/guradb-video-preview-macos-arm64-docker-linux-arm64.pyz及相邻原.pyz.json；平台沿[本机预览](local-preview.md)Mac-arm/系统Python3.9+/既有09bc Docker条件。receipt需来自可信交付来源，SHA校验不是发行签名。安装prefix须不存在。以下实际原样消费者与官方SDK链待独验后补齐，不以预期输出冒已执行结果。

```sh
GURADB_VIDEO_SHA=$(/usr/bin/python3 -c 'import json; print(json.load(open("artifacts/guradb-video-preview-macos-arm64-docker-linux-arm64.pyz.json"))["sha256"])')
/usr/bin/python3 artifacts/guradb-video-preview-macos-arm64-docker-linux-arm64.pyz install --sha256 "$GURADB_VIDEO_SHA" --prefix /tmp/guradb-video-preview
GURADB_VIDEO_CLI=/tmp/guradb-video-preview/bin/guradb
GURADB_VIDEO_DATA="$PWD/artifacts/video-evidence-demo"
"$GURADB_VIDEO_CLI" --data-root "$GURADB_VIDEO_DATA" search --config /data/config.json --query sintel --top-k 2
```

预期唯一sintel-video命中，video/x-msvideo/900000000002/videos/900000000002.avi。下面直接取实际Rust返回ID/SHA读取完整bytes，再以既有工程FFmpeg从这些返回bytes真实解码；RGB摘要来自非作者对原派生文件的独立reader真值。FFmpeg与Python仅工程客户端，不进入Rust运行时。外层CLI等待35秒，给既有20秒工作界加10秒清理留余量；Rust10秒与launcher原界不变。

```sh
/usr/bin/python3 - "$GURADB_VIDEO_CLI" "$GURADB_VIDEO_DATA" "$GURADB_FFMPEG" <<'PYCLIENT'
import hashlib, json, subprocess, sys
cli, data, ffmpeg = sys.argv[1:]
def call(*args):
    p = subprocess.run([cli, '--data-root', data, *args], check=True, capture_output=True, timeout=35)
    return json.loads(p.stdout)
result = call('search', '--config', '/data/config.json', '--query', 'sintel', '--top-k', '2')
assert len(result['hits']) == 1 and result['hits'][0]['doc_id'] == 'sintel-video'
asset = result['hits'][0]['media']
assert asset['asset_type'] == 'video/x-msvideo'
media = call('media', '--config', '/data/config.json', '--asset-id', asset['asset_id'], '--source-sha256', result['source_sha256'])
raw = bytes.fromhex(media['bytes_hex'])
assert len(raw) == media['media_bytes'] == 221902
assert hashlib.sha256(raw).hexdigest() == asset['media_sha256'] == '5d3147365cb8e158dc9ad077acb8cbbc373b197cdbb6ee21aacf54ca80f4a149'
video = media['video']
assert video == dict(container='avi', encoding='bgr24', width=160, height=90, row_order='top_down', row_stride=480, frames=5, rate_num=5, rate_den=1, duration_num=5, duration_den=5)
frames = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-threads', '4', '-i', 'pipe:0', '-map', '0:v:0', '-an', '-filter_threads', '1', '-filter_complex_threads', '1', '-threads', '4', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'], input=raw, check=True, capture_output=True, timeout=30).stdout
assert len(frames) == 5 * 160 * 90 * 3
assert hashlib.sha256(frames).hexdigest() == 'd39e1463a788a1fbc151e771bbdc83bf9848a3a500c05f08015faaaab0b8e2e3'
print('sintel-video video/x-msvideo 221902 bytes 5 frames 160x90 5fps verified')
PYCLIENT
```

也可直接重用交付bundle内的corpus.jsonl（资产相对videos/audio/images目录），输出到全新artifacts/video-replay，复核Parquet自动SHA与同媒体字节；不需ignored TASK脚本或全段MP4。

```sh
.venv/bin/python scripts/prepare_text_corpus.py --input artifacts/video-evidence-demo/corpus.jsonl --output-dir artifacts/video-replay
"$GURADB_VIDEO_CLI" --data-root "$GURADB_VIDEO_DATA" view prepare --store /data/store --config /data/config.json --request-id video-a
"$GURADB_VIDEO_CLI" --data-root "$GURADB_VIDEO_DATA" view publish --store /data/store --request-id video-a
"$GURADB_VIDEO_CLI" --data-root "$GURADB_VIDEO_DATA" view search --store /data/store --view current --query sintel
"$GURADB_VIDEO_CLI" --data-root "$GURADB_VIDEO_DATA" mcp --store /data/store
```

官方SDK沿[原stdio客户端](local-mcp.md)，将query改sintel，使用guradb_search返回的具体view_id与其result.hits[0].media.asset_id调用guradb_media；核result.media_sha256/完整bytes_hex和video对象同上，不能从另一资产成功串成命中证据。工具仍3个，无新参数。旧WAV/JPEG及跨current旧view不得混源；caller保完整store，无自动GC。只core-limited；完整M2/视听语义/性能规模/长稳/强化覆盖与发行均未认证。
