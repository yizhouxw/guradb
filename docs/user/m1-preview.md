# 本机图文检索与固定样本消费（本机受限候选已验）

本页串起已安装的Rust预览入口与已有小输入，给出同源工程组合对照。范围是macOS arm64主机、预置Linux ARM64 Docker、可信单用户、本地Parquet、三个JPEG、15条原caption及四条刷新版本。不是完整M1/P0、生产发行、商业相关性或性能认证。当前无下载、模型推理、服务注册和全局设置。

## 前置与操作

需要当前MCP安装包`guradb-mcp-preview-macos-arm64-docker-linux-arm64.pyz`，SHA256为`63fd9737491fefc86617ba1f967b0b1db06a1ed2a7f8cf18745abcc20c871dee`。其中Rust engine SHA为`e03d3807ad2831650f444fe756bccc83f51b48e4a3f11130570c96e250c221b8`，生产载荷源为`e32dc3992f4f4cdde1929cbe1d1ff735f7f708c3`；本页及离线客户端随仓库版本保存。没有新增Rust或包装载荷。旧797b安装包依赖的181镜像已经丢失，不能代用。

本机已存在runtime完整ID为`sha256:09bc0a87408c56bd4fe912df3ba3d499ea2279ea32cdeddf051a7a3dd3ddb52f`。缺失时doctor拒绝，不自动pull；具名引用不保证外部清理后永久可用。安装物本身不包含Docker镜像。[安装说明](local-preview.md)和[MCP说明](local-mcp.md)保留平台与生命周期边界。

输入根显式包含[小输入清单](m1-inputs.json)的既有文件：`clip-real-model-demo`、`local-view-refresh-demo`及`view-vector-sample-demo`。清单列出原Parquet、完整feature、八个原query/text及模型来源manifest的SHA与三张图片来源；不依赖ignored TASK脚本。原源只读，不扫raw ZIP，不补缺源或重造相似数据。当前教程不提供联网bootstrap；缺少这些现有输入就明确失败。

标准SDK需已有Python3.12/MCP1.12.4环境与[兼容锁](mcp-client-requirements.lock)；框架/组合需已有Python3.12.12、PyArrow22.0.0、NumPy2.5.4、PyTorch2.15.0和Pillow13.0.0环境。不修改主venv或CLIP环境。以下是本机已验证路径示例，其他机器须显式提供等价既有环境，未认证跨平台安装。

在此仓库版本目录运行，`WORK`必须是新的相对`artifacts/`子目录，拒绝覆盖：

```sh
INPUTS=/Users/chad/dev/guradb/artifacts
PACKAGE="$INPUTS/guradb-mcp-preview-macos-arm64-docker-linux-arm64.pyz"
SDK=/Users/chad/dev/guradb-data/offline-envs/mcp-client-py312-20261030/bin/python
FRAMEWORK=/Users/chad/dev/guradb-data/offline-envs/clip-vit-b32-py312-20261030/bin/python
WORK=artifacts/m1-demo
/usr/bin/python3 scripts/m1_preview.py prepare --inputs-root "$INPUTS" --package "$PACKAGE" --work-dir "$WORK"
/usr/bin/python3 scripts/m1_preview.py tutorial --work-dir "$WORK" --sdk-python "$SDK" --framework-python "$FRAMEWORK" --keyword kitchen
"$FRAMEWORK" scripts/m1_compare.py --work-dir "$WORK"
```

准备器拒绝WORK路径中的symlink/父级跳转，先验证声明的小文件与冻结来源摘要，再复制到独占目录，保持Parquet与feature bytes不变，生成配置/固定成员。query向量与space逐字段不变，只将目标source SHA绑定到对应版本；A/B原q01仅source不同已核实。B其余七份是caller目标绑定，不是新模型export或新相关性证据，前后文件SHA写入`inputs.json`。源bytes、完整Docset或space不匹配由Rust/组合拒绝；没有手改GuraDB catalog。

教程逐步执行checksum安装/doctor/capabilities，公开prepare/publish A，SQL投影、可换词BM25、精确vector/hybrid、命中返回asset/view的准确媒体，再以官方SDK读取；公开发布B后核current改变与旧A证据保留，最后通过已安装`prefix/lib/engine`读取旧A固定样本。reader显式`--binary`与`--runtime-image`必须成对，完整ID检查，无研发target依赖。代码和配置仍是外部准备/客户端，不是托管writer或Python在线数据库。

关键词可换为受支持ASCII词；无命中时不会伪造图片，当前纵向教程的非空hit步骤会明确停止。通用文本准备、SQL和查询语言白名单见[alpha手册](simple-alpha.md)。`tutorial.json`保存纵向结果，`comparison.json`保存完整对照，`reader/membership.json`和`reader/epochs.json`保存成员、字节/像素摘要与尾批。失败不计完成；保留独占工作目录用于核查，修正后换fresh目录，不能靠覆盖旧输出消除失败。

## 预期与边界

A source为`8eaaa37c…`、15 Doc，B为`d873f876…`、4 Doc；完整view ID由source和feature bytes共同确定。kitchen返回的真实397133媒体应为200576B/SHA`09e1d25c…`，但客户端始终从真实hit取asset与view，不能硬编码该ID冒命中链。刷新后旧A reader仍train10/validation5，两个epoch的批次均为train `[4,4,2]`、validation `[4,1]`，成员、媒体字节和32×32 uint8 CHW像素应与原源对照一致，不是训练结果复现。

| 入口 | 已有受限能力 | 明确未接通 |
| --- | --- | --- |
| 安装CLI | query/search/media/vector/hybrid/sample；公开prepare/publish完整view | HTTP/PG、远端对象/共享授权、GC/pin平台 |
| 标准MCP SDK | 三只读query/search/media；媒体要求显式固定view | vector/hybrid/sample、更新、全局注册 |
| 框架客户端 | 固定source/feature view、seed0 asset-group split、真实DataLoader两epoch/尾批 | 训练优化、encoder、分布式训练、吞吐认证 |

外层等待给安装75s、SDK95s、reader155s，以先让原内层安装60s+10s清理、MCP75s+10s清理、reader120s+30s清理执行；没有增加内层工作预算。

原Rust512MiB/4CPU、源32MiB/decode64MiB/feature8MiB/output2MiB/N200/TopK20及reader4GiB/4线程/120s工作+另30s清理保持。比较实际只有15/4 Doc。每位作者/独验各至多一次完整教程、一次完整比较及一次有缺陷的定向修复；不重跑旧模型/故障矩阵。新增owned≤1GiB，单安装engine消费者、产品/组合/reader串行。工作目录含安装与受支持小输入，用完可由其创建者按归属删除；不要删除原输入、三个旧安装物、模型/SDK环境、cache或runtime引用。

caption许可为CC BY4.0，图片许可/摄影者归属分别沿原COCO/Flickr来源，不能把caption许可套到图片；未知归属仍UNKNOWN。特征沿官方LAION固定revision/既有card证据，English/域内小样本范围不变；原六个可判query、NONE和UNKNOWN标签保留，既有小样本BM25无语义优势结论不改写。

## 同源组合比较怎样解读

选定已有PyArrow22解码、NumPy2.5.4数值与PyTorch2.15消费，加明确的离线应用协调代码。它们不是原生FTS数据库；`m1_reference.py`负责ASCII tokenizer、BM25(k1=1.2,b=.75)、scaled-f64 cosine、完整rank RRF60、source/feature复核、媒体和asset-group选择。组合不宣称SQL解析兼容，只比较doc_id/text完整排序投影。可核官方接口：[Arrow22 Parquet](https://arrow.apache.org/docs/22.0/python/parquet.html)、[NumPy norm](https://numpy.org/doc/stable/reference/generated/numpy.linalg.norm.html)、[PyTorch DataLoader](https://docs.pytorch.org/docs/2.15/data.html)。

两方用同Parquet/source、完整Doc/asset/feature/space、原八query与同单用户保留责任。A/B各八query的BM25/cosine/RRF共48项先比完整排名、score与解释/身份；数值容差沿既有1e-12 abs+rel，不能据此合并同分或改变顺序。view search固定Top10，因此完整A15 BM25对照使用同固定source的direct-config Top20；vector/hybrid固定view Top20。不能拿Top10冒完整15。组合也做两版投影、成员、三媒体准确bytes及真实框架消费。

成本只记录实际步骤/调用/时间和可观测bytes：Rust每次fresh CLI的整个Docker/完整性检查边界，Reference的首次物化、复用物化及q01/q02各一次cold-process与对应Rust查询分别列；MCP同一stdio会话两次同词查询是transport reuse，不称数据缓存。OS页缓存/容器热度、内部物理磁盘I/O与历史首次接入人时UNKNOWN。不drop-cache，不拿批处理和串行、不同验证/治理边界算加速，不作统计显著性、规模或客户价值外推。

| 责任/成本 | GuraDB入口 | 所选离线组合 |
| --- | --- | --- |
| 首次接入 | 校验包、预置Docker、显式准备输入；客户端环境另给 | 既有Arrow/NumPy/框架环境、应用协调代码及同样的输入准备 |
| 版本/刷新 | Rust校验并owned捕获source+feature，公开prepare/publish，显式旧view | 应用保留两份固定源/feature，逐次摘要/成员复核，完整ready后原子写自己的current指针 |
| 追溯与拒绝 | 返回source/view/feature/query身份、原媒体与明确错误 | 应用必须显式实现身份、分析器、完整排名、保留、错误和同步；未宣称原生库自动提供 |
| 存储/物化 | 输入副本、owned view副本、安装engine和预置runtime | 同输入副本、内存Doc/vector物化与应用指针；环境存储另列 |
| 已知不等价 | 现有受限SQL/公开view、进程预算与恢复证据 | 仅投影SQL；路径检查更严，未认证同等崩溃/发布fence/通用错误code |

应用代码与产品Rust实现分开记账；比较器/断言不计产品能力。不用总代码行数或功能数直接说收益。两方内部验证、启动、物化与治理开销不同，数值等价只说明所选小输入结果可对账。非作者fresh入口与独立原源真值已核：48项完整序/score、两版投影/成员、六媒体及真实两epoch/像素/尾批一致，最大数值差5.55e-17；V1 query provenance与WORK link缺口经V2前置拒绝/正常payload不变定向修复。没有证明普遍性能或企业价值优势。

本机一次观察（无统计/冷存储保证）：对照58个Rust CLI请求输出逻辑1973945B；Reference A/B各物化一次，应用实际读取25347250/3885696B（含摘要复核与reader），不等于物理磁盘I/O。q01/q02各一次Reference cold-process为0.141/0.123s；MCP同会话两次同词查询为0.066/0.067s，互不当成同种性能样本。Rust reader消费4252630B、8.470s、RSS223969280B；Reference直接字节reader同量约0.095s、RSS242679808B，调用与校验边界不同，未显示Rust latency优势。比较算法阶段Reference进程RSS70172672B；Rust512MiB是配置上限，未测实际peak，不能拿二者比节省。

该次owned约165236298B，单prefix160054794B、输入2316209B、owned store1066751B；预存runtime image逻辑Size526667700B另列，不当host新增物理占用。教程13个顶层process包含SDK/reader封装，不能冒全部Rust请求：SDK另外5个tool调用/3个CLI，reader31个Rust调用。历史接入工时、物理I/O、OS缓存仍UNKNOWN；payload重用没有新engine构建成本，正常门禁耗时不作为产品benchmark。

## 与完整目标的关系

| 目标 | 本页有限覆盖 | 尚缺 |
| --- | --- | --- |
| M1.1–1.3 / J2 | 本地准确媒体、ASCII BM25、外部固定特征精确排序/融合、共同身份 | 新业务语料/中文相关性、ANN、Graph、远程对象和共享授权 |
| M1.4 / J4 | 固定成员/asset防泄漏、旧view真实框架消费 | 共享pin/GC、撤权、更多框架、训练结果/吞吐 |
| M1.5 / J1,J5,J6 | 两版本完整重建/就绪发布、旧view与预览安装/诊断/MCP教程 | 正式dataset/schema/托管导入、湖Snapshot、增量/双fence、分布式部署/恢复、完整发行 |
| J3 | 现有限SQL投影/过滤/排序/去重子集 | 参数、JOIN、聚合、更宽数值及共同多入口合同 |

六条完整旅程与全部P0仍未完成，规划文档的历史基点不改写为当前成果。本包不启动M2；建议下一最小目标先做单机一种托管批量导入的dataset/revision身份、持久operation状态与公开重启对账，再接一种真实外部对象/湖输入，分别先冻合同、预算与独立真值。不是继续堆固定COCO演示，也不先铺完整目录/调度平台。
