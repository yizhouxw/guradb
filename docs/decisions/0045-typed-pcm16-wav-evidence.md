# ADR0045：同固定输入中的类型化PCM16 WAV证据

状态：已接受且受限组件真实独验通过；2026-10-31。延续ADR0031/0032/0036/0039，现单机Rust证据路径扩一受限音频类型，无新服务/模型/依赖。media-v1 JPEG响应及来源不变；media-v2使用asset_id/path/type与原media_version/bytes/SHA，严格新9列文本语料，类型、ID、路径、源SHA和实际内容共同对应，不只返回locator。

完整WAV白名单为RIFF/WAVE/fmt16/PCM1/44100Hz/mono或stereo/16bit/唯一fmt后data/非空对齐帧，拒多chunk、压缩、float和未知布局，元数据来自Rust已验头，独立reader实际消费全PCM帧。v2音频不沿JPEG/CLIP feature、vector/hybrid/sample或feature-view；文本是外部文字，不ASR。旧JPEG回归沿既有真实字节，不重启图像/模型矩阵。三资产/200行/512KiB/media、原进程/源/Arrow/输出与RPC预算保持，全部固定view/source和RAII/失败清理沿用。

来源、许可、确切SHA与先行支持/拒绝见用户手册audio-evidence。所有预览产物/真实输入不入Git；新第9具名包与build sidecar同时交付，唯一fresh同prefix CLI+官方SDK，原B/H/M正常core门禁及独立原真值验收。重大cache/build/包/consumer共存先判1GiB准入，M证据归档后先guard退本片new test/rmeta再包/consumer，旧缓存不删；观察代理与物理峰及预算资格分列，未证不得PASS。
