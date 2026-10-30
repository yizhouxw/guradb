# ADR0046：有界原始像素AVI视频证据

状态：已接受，受限组件实现与非作者验收通过；2026-10-31。延续ADR0045媒体v2身份与全部预算，仅增加video/x-msvideo/videos/12位ID.avi，不新增协议或服务。

选择AVI1.0单vids、handler为0或DIB空格、BITMAPINFOHEADER40/BI_RGB0/planes1/24bit BGR。宽1..320，signed高非0且abs≤240，row_order按符号明确；row_stride=align4(width*3)。每帧完整原像素bytes等于stride*abs(height)，不依赖外部codec或新增Rust库。整数fps1..30、scale1、frames1..30；avih微秒/帧floor(1000000/rate)与strh rate、各帧数、00dc或00db原帧与idx1同ID逐条offset/size/keyframe及movi实际帧一致，时长输出精确frames/rate。AVIH flags含0x10且仅可再含0x100/0x800，stream flags0，其余拒；已知byte-rate/buffer/quality/ppm提示字段不驱动分配或声称新语义。源512KiB先限，长度/偏移checked计算，不按建议buffer字段分配。全文件最多128个chunk，已知JUNK/INFO按完整边界跳过；未知语义/其它轨道/压缩/AVIX/indx/rec/尾垃圾明确拒绝，不忽略不支持行为。

media v2新增video对象字段container=avi、encoding=bgr24、width、height、row_order、row_stride、frames、rate_num、rate_den、duration_num、duration_den。JPEG v1及WAV v2 JSON保持，旧view布局仍可读；新capture及state共同最多3资产，store预算不扩。view publication/查账必须包含videos目录，无新可变依赖。v2 feature/vector/hybrid/sample拒例沿原合同；普通managed未验不一概承诺。

真实Sintel许可/载体/静音派生和本机用户复现见用户页video-evidence。独立FFmpeg消费真实帧；结构完整的任意BGR像素本身是合法raw视频，不伪称语义损坏检测。拒例以布局/源身份/索引/时间/边界为准。原MP4容器/压缩/音轨仅离线reader，不作生产支持。另一候选MJPEG+小decoder因新增dependency hash路径可能多占一个163MB main而退出，实际0新依赖/下载/registry写；保留选型依据，不以更小负载宣性能收益。

资源：先完整target/registry S0、native-only实测hash路径及全改写字节，再判fulltest。jobs1，证据归档后guard退新7test，clippy仅退自身新check-onlyrmeta；M归档后退临时cache再包/wholeconsumer。允许具名保留必要paired build-rmeta≤64MiB，真实身份/持续计账/下包S0，非临时删除。全时物理峰未知即UNKNOWN，不改旧Q04 NOT_PASSED。
