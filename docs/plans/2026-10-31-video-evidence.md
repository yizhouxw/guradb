# 变更计划：固定短视频的原字节与真实帧消费

状态：受限组件作者/非作者验收已过，正常H-M及精确包消费/最终退出待闭合。B c75b87e39ca3717546f6caa964142cfe175f4825；codex/video-evidence；receipt ca4d24dcfd274e02a0edeecda0080c27；checkpoint checkpoints/20261030T230614Z-before-video-evidence-db5bd4f6。无已有用户dirty。PM六规划MD不在写域。

## 范围与真值

docs/user/video-evidence先行，ADR0046冻结一种AVI1/BI_RGB/BGR24单视频；Rust media/AVI/path/capture/state及现MCP描述、现离线prepare与API导航必要同步。无新Rust依赖、codec平台/模型/服务；原MP4只是许可离线输入、silent缩放降帧派生，不冒原质量或视频理解。用户文本sintel命中→具体source/view/asset→完整221902B→独立ffmpeg真实帧，三资产仍含既有WAV/JPEG。用户小bundle≤4MiB，原始MP4临时退。

## 不变量和恢复

每媒体512KiB/3资产/200行、旧source/decode/output/RPC/CPU/RSS/timeout预算原值。9列v2关联和旧v1兼容；capture/publish/status/recover均覆盖videos并共同3上限。错型/错ID/替换/链接/缺失/格式-时间-索引-帧冲突/音轨/压缩/AVIX/超额必须拒且无成功payload，之后合法恢复。旧view跨current固定source/媒体；无自动GC。持久view新目录是新增可读类型，旧reader不能消费video，回退须保新store与包，不删除用户输入。未知发布先公开status/recover，不重写提交历史。

## 阶段与资源

07:00:46新120min，首07:20:46/行为08:00:46/M+fresh08:30:46/硬09:00:46，末30min退出。S0-ARCHIVE在任何Cargo借写前实际完整target及registry。新owned1GiB，原/派生源、TASK/commonGit、全改写旧cache、新cache、包sidecar、wholeconsumer复制zip/prefix/data全额计。native-first测实际hashedmain及rlib；fulltest原音频phaseceil1065554432仅参考，不能无新实测继承。jobs1/正常fmt-clippy-test阈值不变，7test归档后guard退再下一clippy；M证据归档后退大临时cache再包/consumer。必要pairedrmeta≤64MiB可development具名移交持续计费。全时峰UNKNOWN不回填，旧Q04超限NOT_PASSED不改。

## 验收与交付

非作者system-test从官方源/许可先冻truth，源窗口与工具SHA锁定，实际raw输出总≤64MiB/元数据≤4MiB/30s512MiB4CPU监督，不落raw帧；native OS监督实录不冒Docker硬限。只必要视频拒例/旧JPEG-WAV与跨current固定兼容，不重旧音频63/CLIP/大矩阵。正常适用完整core原B-H-M、normalhook/提交后check/checkpoint/taskfinish及PR，精确M+第10包原sidecar、唯一fresh System3.9原样入口+同prefix官方SDK/09bc/networknone/两mount。owner完整manifest安全退出/Root归还/固定REPORT-CLEANUP-BOUND后最后非作者纯读/真实SEAL；所有原失败及逾点保。

## 实际结果

作者fmt/clippy/原7测试binary共66tests PASS；非作者71 CLI/信号事件+官方SDK7（6成功1预期拒）、独立原源帧/AVI bytes/帧/时间与旧view兼容通过。公开原样installed PYCLIENT保留唯一M消费者验证；普通H-M完整门禁、包/sidecar、owner-final仍待。许可源Sintel已一次取得4372373B，b670602f…，原载体历史UNKNOWN；W3Schools403和W3C BBB超8MiB未GET原件保留。实际派生5d314736…，221902B/top_down/5帧/5fps/160x90；真实原窗24帧+派生5帧先行oracle9a288260，candidate返回再5帧核同，raw累计29946240B；不宣完整52秒解码或原载体转换史已知。选型由MJPEG转零依赖raw避免新增depgraph main双路径风险，生产9Rust已冻结，原首Rust07:21:05.677晚首点19.677秒保留。
