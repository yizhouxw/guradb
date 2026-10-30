# 固定输入中的真实PCM16 WAV证据

状态：受限Rust组件已通过真实非作者验收；2026-10-31。适用本片第9个audio预览包及同源用户数据；精确main安装消费证据见本片交付报告，完整M2/音频泛化与发行未认证。可信单用户/本地单Parquet/现Rust CLI及既有MCP，不提供ASR、音频模型、转码、压缩音频、视频或时间切片。文本检索只匹配外部提供的标题/描述。

新增media版本2以asset_id/int8、asset_path/text、asset_type/text、media_version/int8=2、media_bytes/int8和media_sha256/text共同绑定同一Parquet。text_version=1/doc_id/text沿用；新混合语料严格9列，不能混用v1字段或混版本。asset_type仅image/jpeg与audio/wav，ID为1..999999999999且跨类型唯一，同ID所有行描述必须相同；路径只能images/12位ID.jpg或audio/12位ID.wav，并与类型匹配。旧v1五媒体列和旧JPEG响应保持兼容，不隐式升级。未知版本/类型、错类型内容或关联、重复冲突、越根/链接/特殊文件、缺失或替换、错误SHA一律拒绝。

WAV只支持完整little-endian RIFF/WAVE、唯一16字节fmt块且PCM格式1、16bit有符号、44100Hz、1或2声道、唯一非空data块；严格校验RIFF完整长度、fmt/data顺序、byte_rate/block_align/PCM帧对齐，拒绝额外/重复chunk、尾部垃圾、RF64/RIFX/float/压缩/截断/其它采样率或声道。返回完整原始WAV bytes_hex及asset_type/asset_path，audio元数据为encoding=pcm_s16le、sample_rate、channels、bits_per_sample、frames；帧数/采样率给精确时长，不把模型或作者推测当元数据。JPEG v2核FF D8 FF前缀与FF D9结尾（不支持JPEG尾部附加bytes），不作新增图像解码或音频特征推断。音频/媒体v2不接vector/hybrid/sample及feature-view，明确拒绝，不能沿用图像CLIP空间。

media上限仍512KiB/3资产/200行，输出2MiB；源32MiB/decode与retained Arrow各64MiB/pool32MiB无spill、512MiB4CPU10s和RPC64KiB请求不变。请求带文本命中返回的asset_id和source SHA；view读取使用返回的具体view_id，MCP媒体工具拒current；CLI view media为保持旧兼容可接current并返回具体解析ID，但准确取证必须显式传检索返回的具体view_id。旧view固定旧source与媒体；不允许刷新current掩盖错源。实际返回完整JSON+exit0才成功；部分stdout不算成功。错误后进程/FD/容器退出与重跑恢复沿原生命周期，不写媒体输出文件。

离线入口复用scripts/prepare_text_corpus.py，新增JSONL形状为doc_id/text/asset_id/asset_type/asset_file，asset_file仍输入JSONL目录内相对普通文件、无链接/越根；类型及原字节经离线检查后写自动SHA config和原source记录，不替Rust确认。原text-only/JPEGv1形状不变，新输出必须是尚不存在的artifacts子目录，错误不覆盖现有文件并清本次部分输出。首例两条外部文字、一真实WAV和一既有JPEG，原始+派生用户bundle≤4MiB，不向Git提交媒体。

真实WAV来源为[PyTorch官方教程资产](https://download.pytorch.org/torchaudio/tutorial-assets/steam-train-whistle-daniel_simon.wav)，[官方文档](https://docs.pytorch.org/audio/2.1/tutorials/audio_io_tutorial.html)列44100Hz/2声道/109368帧/PCM16。2026-10-31实际取得437516B，SHA256=762b6783be7f20aa8be03812eeb33184bb5b1497db7422607a70b5d441fc45e9。上游作品[Steam Train Whistle，Daniel Simion](https://soundbible.com/2177-Steam-Train-Whistle.html)采用[CC BY 3.0](https://creativecommons.org/licenses/by/3.0/)，须保作者/作品/许可链接和变更说明。上游约1.05MB与Torch样本大小不同，Torch此前剪辑/转码历史UNKNOWN；这里只宣称逐字节保留所取Torch资产，不宣称SoundBible原作字节未变。JPEG来源/归属与文字许可分列，仍保原COCO边界，不由WAV许可覆盖。

下面示例保留已有JPEG，不下载图片。先准备新输入目录，将合法取得的Torch WAV置为train.wav；样本SHA必须等于上文762b6783…。JPEG使用本机既有COCO397133，图像版权/摄影者仍沿原归属UNKNOWN，不由WAV许可覆盖。输入正文是本例提供的外部文字，不声称音频识别结果。

```sh
mkdir artifacts/audio-input
cp /path/to/steam-train-whistle-daniel_simon.wav artifacts/audio-input/train.wav
cp artifacts/clip-real-model-demo/corpus/images/000000397133.jpg artifacts/audio-input/kitchen.jpg
cat > artifacts/audio-input/corpus.jsonl <<'JSONL'
{"doc_id":"train-whistle","text":"Steam train whistle Daniel Simion field recording audio","asset_id":900000000001,"asset_type":"audio/wav","asset_file":"train.wav"}
{"doc_id":"coco-kitchen","text":"Existing COCO kitchen photograph image 397133","asset_id":397133,"asset_type":"image/jpeg","asset_file":"kitchen.jpg"}
JSONL
.venv/bin/python scripts/prepare_text_corpus.py --input artifacts/audio-input/corpus.jsonl --output-dir artifacts/audio-evidence-demo
```

输出2条/9列，config.json自动填真实Parquet SHA，media bytes逐字节复制。准备输出已存在、缺源、错类型、非上述PCM布局/越界均拒，旧输入不覆盖；离线验证不替Rust核验。首次输入目录/输出目录须未存在，重做换新目录。数据准备需现有工程venv与pyarrow，不属于在线服务或预览包依赖。

新安装物为artifacts/guradb-audio-preview-macos-arm64-docker-linux-arm64.pyz及相邻.pyz.json。复用[本机预览安装](local-preview.md)的Mac-arm/系统Python3.9+/既有09bc Docker条件；相邻原build receipt须来自本机可信交付来源；下面从该receipt读取SHA给installer实际校验，不手填占位，两个文件本身不代表发行签名。install到未存在prefix。以下设GURADB_AUDIO_CLI为该prefix/bin/guradb，GURADB_AUDIO_DATA为准备结果的绝对路径，均由使用者赋实际路径，没有额外helper/Task脚本。

```sh
GURADB_AUDIO_PYZ_SHA=$(/usr/bin/python3 -c 'import json; print(json.load(open("artifacts/guradb-audio-preview-macos-arm64-docker-linux-arm64.pyz.json"))["sha256"])')
/usr/bin/python3 artifacts/guradb-audio-preview-macos-arm64-docker-linux-arm64.pyz install --sha256 "$GURADB_AUDIO_PYZ_SHA" --prefix /tmp/guradb-audio-preview
GURADB_AUDIO_CLI=/tmp/guradb-audio-preview/bin/guradb
GURADB_AUDIO_DATA="$PWD/artifacts/audio-evidence-demo"
"$GURADB_AUDIO_CLI" --data-root "$GURADB_AUDIO_DATA" search --config /data/config.json --query train --top-k 2
```

该search只有train-whistle命中；media身份是audio/wav、asset900000000001、audio/900000000001.wav，source_sha256等于刚生成config SHA。下面工程客户端直接取Rust返回ID/SHA，不离线计算命中；wav reader实际读完整PCM帧，原WAV与返回字节逐SHA核同。

```sh
/usr/bin/python3 - "$GURADB_AUDIO_CLI" "$GURADB_AUDIO_DATA" <<'PYCLIENT'
import hashlib, io, json, pathlib, subprocess, sys, wave
cli, data = sys.argv[1:]
def call(*args):
    p = subprocess.run([cli, '--data-root', data, *args], check=True, capture_output=True, timeout=20)
    return json.loads(p.stdout)
hit = call('search', '--config', '/data/config.json', '--query', 'train', '--top-k', '2')
assert len(hit['hits']) == 1
asset = hit['hits'][0]['media']
assert asset['asset_type'] == 'audio/wav'
media = call('media', '--config', '/data/config.json', '--asset-id', asset['asset_id'], '--source-sha256', hit['source_sha256'])
raw = bytes.fromhex(media['bytes_hex'])
assert hashlib.sha256(raw).hexdigest() == asset['media_sha256'] == '762b6783be7f20aa8be03812eeb33184bb5b1497db7422607a70b5d441fc45e9'
with wave.open(io.BytesIO(raw), 'rb') as reader:
    assert (reader.getframerate(), reader.getnchannels(), reader.getsampwidth(), reader.getnframes()) == (44100, 2, 2, 109368)
    assert len(reader.readframes(reader.getnframes())) == 437472 and reader.readframes(1) == b''
print('train-whistle audio/wav 437516 bytes 109368 frames verified')
PYCLIENT
```

固定view/MCP沿同一公开路径：

```sh
"$GURADB_AUDIO_CLI" --data-root "$GURADB_AUDIO_DATA" view prepare --store /data/store --config /data/config.json --request-id audio-a
"$GURADB_AUDIO_CLI" --data-root "$GURADB_AUDIO_DATA" view publish --store /data/store --request-id audio-a
"$GURADB_AUDIO_CLI" --data-root "$GURADB_AUDIO_DATA" view search --store /data/store --view current --query train
"$GURADB_AUDIO_CLI" --data-root "$GURADB_AUDIO_DATA" mcp --store /data/store
```

MCP须用官方SDK完成initialize/initialized，再guradb_search(view=current,query=train)，把返回具体view_id与命中asset_id原样传guradb_media；返回仍为原Rust JSON/完整bytes_hex与audio元数据。MCP media current拒绝，CLI取证也应固定具体ID。工具仍3个，没有新客户端筛选/排名语义。两source发布后旧view始终读旧Parquet与旧media；caller保完整store，无自动GC。只读取外部描述文字；不宣称ASR、音频CLIP或语义优势。上述新增准备/证明路径与参数/拒例由本片有限独验覆盖，旧JPEGv1无新参数兼容；完整M2/性能长稳/强化/发行未授。
