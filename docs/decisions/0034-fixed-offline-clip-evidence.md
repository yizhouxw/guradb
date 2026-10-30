# ADR0034：固定真实CLIP离线证据与Rust输入边界

状态：已接受，2026-10-30；固定真实模型/小域证据独验PASS，非通用模型或发行认证。

现有Rust精确cosine/RRF首包只证明外部特征的数值与输入身份，不能证明真实模型或语义。新增独立可删的Mac arm64/CPython3.12离线环境与hash锁定官方wheel，用一个固定LAION CLIP ViT-B/32 LAION2B revision1a25a446712ba5ee05982a381eed697ef9b435cf，优先其官方OpenCLIP safetensors（ac4f8c4b…）而不执行pickle/远程自定义模型代码。Rust源码、依赖、格式、预算、服务范围不变，Python仅离线材料准备。

图像encoder在CPU fp32 eval/inference_mode生成512D，每asset一次编码后如实复用到同图各caption DocID；query由同模型text encoder产生。保留原始投影f32→f64值，既有Rust再按原scaled-L2/cosine合同计算。sourceSHA/DocID全集/asset/媒体SHA、权重/config/card、OpenCLIP代码与BPE、预处理recipe/环境lock/helper SHA、实际解释器均记录，feature/query同完整space。来源声明、数值真值、先冻8query/标签的小域观察、泛化/业务优势分别验收，NONE不期待没有拒绝阈值的向量返回空，UNKNOWN不算命中成功，文档排名与离线asset首现顺序分开。

仅原三JPEG/15caption，图片解码只用于必要预处理，不新增媒体/下载数据集/账户/云/费用/ANN或模型服务。模型应用payload≤750MiB、依赖预编译wheel≤2GiB、增量磁盘≤6GiB；算子线程4、单导出≤600秒、RSS≤4GiB，父进程每250ms监控/越界杀子进程并清本次新输出，worker结束再核OS历史峰值；不声称采样是操作系统硬RSS限额。失败/取消不删除既有cache，已有输出拒绝覆盖；只保明确命名的唯一模型cache/离线env/小用户bundle，删wheel中间副本和临时树。

官方[固定模型卡](https://huggingface.co/laion/CLIP-ViT-B-32-laion2B-s34B-b79K/blob/1a25a446712ba5ee05982a381eed697ef9b435cf/README.md)的MIT标签/研究/English/域内测试限定保留，不认证训练数据权利、部署或业务适用。原caption与photo来源/许可/UNKNOWN独立保留。当前只有core-limited和本固定域可复查观察；完整M1/P0、规模、覆盖、性能/长稳/发行仍缺证据，不把第三方模型卡通用指标变成本产品baseline。
