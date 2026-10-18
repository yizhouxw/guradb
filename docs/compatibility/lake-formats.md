# 数据湖与多模态格式：当前支持及后续规划

状态：当前实现按 **2026-10-18** 源码及[12域复审](../reviews/2026-10-18-capability-architecture.md)对账；后续生态规划仍待独立验收。外部规范资料沿用 **2026-10-17** 的调研记录。

机器可读支持范围见[能力清单 v1](../../api/capabilities/v1.json)及其[schema](../../api/capabilities/v1.schema.json)。它随源码版本解释，是离线合同，不是 HTTP 发现端点，也不能证明某个部署已启用能力或通过本轮门禁。实际验收仍绑定对应 commit 的报告。

## 当前支持白名单

M0 SQL 由 Rust/Arrow/DataFusion 执行；M1/M2 的 scan/search/graph/export 作业由独立 Python/PyArrow 服务执行，Snapshot 仍是可信操作者入口。二者不是统一 SQL 融合入口，客户端不能把 M1/M2 格式或检索能力套用到 M0 SQL。默认读取已发布 read view，源提交与视图发布分别处理，见[接口合同](../interfaces/query-and-clients.md)及 [ADR 0004](../decisions/0004-snapshot-and-index-publication.md)。

| 路径 | 当前可用范围 | 明确不支持或未验证 | 实现与验收依据 |
| --- | --- | --- | --- |
| M0 Parquet manifest v1 → SQL | 操作者固定文件集合、schema、对象大小和 SHA-256；可固定 S3 version_id；`int8`（int64）/`text`/`bool` 与 NULL；有界全对象校验/解码后执行 SQL 白名单。已测 PyArrow 22/Snappy、SeaweedFS 3.97 与受信本地文件 | 通用湖表发现、Iceberg SQL、目录枚举、row group/page 裁剪、通用 Parquet 类型/codec 兼容；无业务写入 | [manifest 校验](../../crates/guradb-common/src/manifest.rs)、[reader](../../crates/guradb-connectors/src/lib.rs)、[M0设计](../design/m0-parquet-http.md)、[M0验收](../design/m0-validation.md) |
| M1/M2 Iceberg v2 → 固定 Snapshot | 显式 metadata URI/SHA-256/snapshot ID；单 schema、单非分区 spec、空 sort order；平面 long/string/boolean 与 Parquet；逐文件核验 field ID/名称/顺序/类型/nullable；Avro 元数据仅 null/deflate codec | REST Catalog 自动发现、v1/v3、position/equality delete 文件、schema/分区演进、嵌套/default/加密、空快照；不忽略不支持的必需语义 | [reader](../../modules/connectors/iceberg.py)、[M1白名单](../design/m1-snapshot-serving.md)、[M1验收](../design/m1-validation.md) |
| M2 显式 append 刷新 | 验证完整 append-only 历史、稳定键和旧源文件身份；从源读取新增 data files，复制已校验旧副本，继承旧记录版本；新视图索引全量重建后单独发布 | 通用 CDC、Continuous、更新/删除/压实、schema/布局变化、旧特征/模型/媒体变化；旧 bundle 缺不可变身份时须显式 Snapshot 建立基点 | [历史验证](../../modules/connectors/incremental.py)、[刷新](../../modules/query/incremental.py)、[正反例](../../tests/contracts/test_incremental.py)、[ADR 0013](../decisions/0013-local-p0-partitions-and-recovery.md) |
| 内部 Lance IVF_FLAT | pylance 0.39.0 构建不可变派生 ANN；记录 dataset version、文件摘要和逻辑键/record_version 映射；全局及分片产物供本项目检索使用 | 外部 Lance 表连接器、LanceDB API、外部 Blob/版本/删除/compaction 兼容；ANN 产物不能独立接受业务写入 | [ANN](../../modules/index/ann.py)、[ANN合同测试](../../tests/contracts/test_ann.py)、[ADR 0012](../decisions/0012-bounded-p0-and-local-workers.md) |
| 训练 manifest/Parquet 导出 | 固定 read view 的**全视图**样本；固定身份、record_version、seed/split、values_json、vector、media_json；Parquet 为 Snappy，int64 在 values_json 中为十进制字符串 | 筛选/列投影样本、任意 SQL/JOIN、框架/epoch/checkpoint 恢复、WebDataset 等训练格式；导出不等于源 Iceberg 写回 | [训练实现](../../modules/connectors/training.py)、[全视图合同测试](../../tests/contracts/test_capabilities.py)、[真实功能验收](../../tests/functional/m1.py) |
| 单机托管 Iceberg append | 可信操作者管理本地 PyIceberg SQL catalog/warehouse；固定 `id/title/active` schema，PG 意图/generation 加贯穿源提交的本地 flock；未知结果先对账；最多32批、10000行，另受字节预算约束 | 公开 HTTP/CLI/MCP 写 API、外部湖原地写回、旁路 writer、跨机器源 fencing、update/delete；worker 不持有源提交权 | [writer](../../modules/connectors/writer.py)、[writer测试](../../tests/contracts/test_writer.py)、[操作入口](../design/m2-running.md) |

当前本地 worker 通过进程或 loopback HTTP 读取共享绝对路径上的产物，不是外部格式连接器或跨机部署。协调器仍加载完整 bundle/rows 并校验产物，不能因已有 serving Parquet 或三个 worker 宣称按需列读取或海量扫描；M1/M2 的32文件/10000行等预算见[M1设计](../design/m1-snapshot-serving.md)。

源文件增量不等于索引增量，也不等于零 I/O：旧 data GET 可省略，但仍有元数据读取、stat/S3 HEAD、旧副本复制与全索引重建。Snapshot reader 会排除 manifest 中标记删除的**数据文件**；这不表示支持 position/equality 行级删除文件，append 刷新会拒绝删除状态和非 append 历史。

新 bundle v2 全文使用 `bm25-global-v2` 全局统计；旧 bundle v1 保持 Tantivy 路径。二者评分/分析器合同按索引版本区分，不能由内部存在 Tantivy 或 Lance 文件推导外部索引可复用。具体兼容见 [ADR 0013](../decisions/0013-local-p0-partitions-and-recovery.md)。本页不开放新的 reader/writer 特性，不改变数据布局或预算；后续支持必须先补正反例与独立互操作证据。

## 1. 目标与承诺方式

长期目标是覆盖主流开放数据湖生态，以及 AI 训练、推理和应用所使用的多模态数据组织方式。生态持续变化，“全部支持”应通过可扩展的连接器和持续维护的兼容清单推进。每次发布都需要列出可验证的版本、功能、读写方向和限制，不使用一个“兼容”标记代替它们。

兼容项至少由以下信息共同确定：

```text
格式 / 规范版本 / reader 与 writer 特性 / 编码与压缩组合
+ Catalog 协议 / 存储后端 / 数据类型映射
+ 元数据发现、扫描、检索索引、训练读取、写入等能力级别
```

例如，“能够读取某个 Parquet 文件”不等于“能够读取使用该文件的 Delta 表”；忽略事务日志或行级删除信息会产生错误结果。外部格式可读，也不意味着能够直接复用其向量、全文或 Graph 索引。

## 2. 兼容对象分层

| 层次 | 本页覆盖对象 | 后续需要定义的边界 |
| --- | --- | --- |
| Catalog 与发现协议 | 当前显式 Iceberg metadata-location；REST Catalog 与其他连接器待设计 | 命名空间、表定位、鉴权、凭证传递、元数据刷新、提交协议 |
| 事务表格式 | Apache Iceberg、Delta Lake、Apache Hudi、Lance table format | 源快照、提交、删除、schema 演进、并发与历史保留 |
| 文件与交换格式 | Parquet、Arrow IPC；后续 ORC、Avro 等 | 类型、编码、列投影、范围读取、统计信息、批次交换 |
| 训练分片与样本格式 | WebDataset、MDS、TFRecord | 分片枚举、样本边界、字段解释、恢复位置与分布式采样 |
| 多维数组与科学数据 | Zarr、HDF5 | 数组形状、坐标与切片、chunk、codec/filter、对象访问 |
| 数据集规范与分发生态 | Hugging Face Datasets/Hub、LeRobotDataset | revision、split、feature schema、目录布局、样本与媒体对齐 |
| 原始媒体与模型资产 | 图片、音频、视频、safetensors | 字节保真、对象引用、媒体解码、时间片与张量读取 |

Hugging Face Datasets 是库及数据集访问生态，Hub 是分发与版本管理入口；它们接入多种底层格式，不能当成单一的通用“湖存储格式”。LeRobotDataset 是结合表格、视频和元数据的数据集规范。Lance 具有文件格式与表格式两层；LanceDB 是基于 Lance 的数据库产品，读取 Lance 不等于兼容 LanceDB 的服务接口或查询行为。[Hugging Face 加载文档](https://huggingface.co/docs/datasets/en/loading)、[LeRobotDataset v3 文档](https://huggingface.co/docs/lerobot/lerobot-dataset-v3)、[Lance 文件规范](https://lance.org/format/file/)、[LanceDB 官方说明](https://www.lancedb.com/blog/what-we-mean-by-multimodal)

## 3. 后续方向性能力矩阵

以下保留**目标和候选设计**，各行包含尚未实现的能力，不能整体作为支持声明；当前可用部分仅以上方白名单为准。阶段与[路线图](../roadmap.md)一致：M0 有界 manifest SQL、M1 固定快照检索与训练导出、M2 独立能力门禁、M3 分布式、M4 发布；“后续”表示尚未进入首条实施链。表内“绑定源版本”描述目标读取语义；“固定清单”表示需要记录不可变对象集合，不能据此宣称源格式拥有事务快照。

| 对象 | 首个接入门禁 | 只读目标与限制 | 写入方向与独立门禁 | 快照 / 可复现读取目标 | 谓词与列投影目标 | 训练读取目标 | 多模态引用目标 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Iceberg | M1 受限 Snapshot | v2/Parquet 白名单；声明是否含 position/equality delete，不支持的必需特性拒绝；v1/v3 后续分别认证 | M2 托管单表串行 append；批式删改、外部原地写回另行验证 | 绑定 snapshot ID、schema、分区规范及保留等级 | 分区 / manifest / 文件统计裁剪，剩余谓词由引擎执行 | M1 生成固定 snapshot 的训练 manifest；流式恢复后续认证 | 二进制列或经约定的外部对象引用 |
| Delta Lake | 后续 | 按 reader protocol 与 table features 协商读取 | 独立 RFC，覆盖日志提交与 writer features | 绑定表版本及对应日志 / checkpoint | 分区与文件统计裁剪、列投影 | 固定表版本扫描；CDC 与训练读取分开 | 二进制或引用列；引用结构另行定义 |
| Hudi | 后续 | CoW snapshot 先行；MoR 完整合并另行验证 | 独立 RFC，覆盖 timeline、并发和表服务 | 绑定完成的 timeline instant 与查询类型 | 按选定读取实现验证分区 / 文件裁剪 | 固定 instant 扫描；增量 / CDC 分开认证 | 元数据列与对象引用，不能丢失 record key |
| Lance | 内部 ANN 为 M2；外部 reader 后续 | 外部 table manifest、file version、Blob 能力分别认证；内部使用不证明外部兼容 | M2 内部派生物化构建；外部业务表写入/并发提交后续设计 | 绑定 dataset version 与所引用对象 | 列投影、过滤与随机读取分别验证 | 固定 dataset version 的批量与随机样本读取另行认证 | 区分内嵌 binary、Blob descriptor 与外部对象 |
| Parquet | M0 | 显式不可变文件 / manifest 扫描，固定 schema/类型白名单 | M1 训练 Parquet/manifest 导出独立验收；不代表湖表写回 | 固定文件集合、对象版本和保留等级 | 列投影；row group / page 统计裁剪分别验证，无统计则扫描 | M1 训练 manifest；分片读取与导出分别验收 | 内嵌字节或应用约定的引用结构 |
| Arrow IPC | 对外格式后续 | 内核 Arrow batch 从 M0 使用；外部 file/stream reader 分开认证 | 结果批次交换及文件导出分别验收 | file 固定对象；stream 需另行记录批次与来源 | 列投影与批次处理；不假设文件统计索引 | record batch 流；不等于训练任务恢复机制 | 保留结构化类型与扩展类型元数据 |
| WebDataset TAR | 后续独立门禁 | 分片枚举、同名组件聚合及原始成员读取 | 固定清单的分片导出独立验收，M1 不依赖该能力 | 固定 shard 清单、对象版本与样本标识 | 默认顺序扫描；成员索引属于附加能力 | 顺序读取、预取、跨 worker 分片 | 保留样本内图片 / 音频 / 视频 / 标注的配对 |
| Hugging Face Datasets / Hub | 后续 | 底层 Parquet / WebDataset 明确子集先行；Hub 元数据/生态另行认证 | 先导出约定布局；Hub 发布独立设计 | 固定 repo revision、config、split 与文件清单 | 随底层 reader；不能笼统承诺全部下推 | streaming 访问、分片与断点语义逐项验证 | 按 features 解释字节 / 路径，保留 dataset 元数据 |
| Zarr | 后续 | v2、v3 分开；先声明 codec 子集 | 数组或 chunk 导出，事务写入待研究 | 固定 metadata 与 chunk 对象清单 | 优先数组切片 / chunk 裁剪；SQL 值谓词另设计 | 按 chunk / patch 生成训练样本 | 数组引用、维度、切片与坐标信息 |
| HDF5 | 后续 | 静态文件、dataset 路径与明确 filter 子集 | 文件导出；在线原地写入待研究 | 固定文件版本；活跃 SWMR 文件单独评估 | hyperslab / chunk 选择；不假设 SQL 统计下推 | chunk / slice 批量访问；对象存储成本实测 | dataset 路径、数组切片与外部依赖 |
| MDS | 后续 | index.json、shard、编码白名单 | 与选定 Streaming 版本互操作的导出 | 固定 index 与 shard 清单 | 样本定位；值过滤默认为读后执行 | shard 缓存、样本顺序、恢复位置待验证 | 保留字段编码与样本关联 |
| TFRecord | 后续 | 二进制 record；Example schema 需明确 | 分片导出与校验 | 固定文件集合及样本 schema | 默认 record 扫描；解析后过滤 | 顺序分片读取；索引属额外设计 | 显式解释 bytes / Feature，不能凭后缀推断 |
| LeRobotDataset | 后续 | 优先研究 v3；v2.1 单独适配 | 数据集导出及元数据一致性另立 RFC | 固定 revision、layout 版本与资产清单 | episode / 时间范围裁剪，底层表格投影 | 按 episode / 时间窗口读取与视频对齐 | 保留相机、帧时间、动作 / 状态、任务与 episode 关系 |
| 图片 / 音频 / 视频原始对象 | M0 引用；M1 最小模态 | 固定对象字节与元数据；逐 codec 解码分别验收，不要求先实现视频抽帧 | 托管对象与元数据写入随 M2 writer；转码属于派生作业 | 固定不可变 key/对象版本并有保留保护；摘要只校验 | 元数据过滤；帧 / 时间范围读取按容器与 codec 验证 | 并发预取与按需解码后续认证 | 统一资产标识、对象定位、字节范围及时间片 |
| safetensors | 后续 | 模型资产登记、header 与张量元数据读取 | 资产上传 / 导出；模型打包另议 | 固定权重文件、分片索引和内容摘要 | 按张量名 / dtype / shape 过滤元数据 | 按需张量读取；不等同于训练样本流 | 模型权重与训练 / 推理数据的血缘关联 |

ORC、Avro、JSON/JSONL、CSV/TSV、NumPy、领域数据集布局等应进入可扩展登记表，根据工作负载补充版本和能力认证。若宣称 Iceberg 或 Hudi 的完整文件格式覆盖，就必须补齐对应底层格式；阶段性的 Parquet 子集应在发现和打开表时明确报告，不能静默遗漏文件。

## 4. 删除与 schema 演进是正确性要求

| 对象 | 需要验证的删除语义 | 需要验证的 schema / 版本语义 |
| --- | --- | --- |
| Iceberg | v2 position / equality delete、sequence number；v3 deletion vector 等按版本验证 | field ID、重命名 / 删列 / 类型提升、分区演进、默认值与新增类型；v4 当前仍在开发，不能归入稳定兼容承诺 |
| Delta Lake | 必须应用源版本的 remove action 与 deletion vector；不能直接扫描目录下全部 Parquet | reader / writer protocol、table features、column mapping、类型演进及启用特性；不认识必需特性则拒绝读取 |
| Hudi | timeline 完成状态、record key、删除及选定 record merger；MoR 必须合并 base 与 log | table version、schema、合并规则与表服务；read-optimized 结果不能冒充 MoR 最新 snapshot |
| Lance | manifest 所引用 fragment 的 deletion file；compaction 后 row address 与索引关联变化 | field ID、data evolution、reader feature flags、文件版本和 Blob 布局；不认识必需特性则拒绝读取 |
| 文件 / 分片 / 数组 / 原始资产 | 不假设拥有通用行级删除或跨文件事务；删除通过拥有方协议或新清单体现 | 不假设目录里的新旧文件同 schema；逐项记录缺失字段、类型映射与扩展类型处理规则 |

Iceberg 的稳定规范目前覆盖 v1–v3，v4 尚未正式采纳；v2 与 v3 的删除机制需要分别认证。Delta 的 deletion vectors 会改变 reader 兼容要求。Hudi 的 snapshot 与 read-optimized 是不同读取语义。Lance 的 deletion files 与 schema 演进具有自身规则，不能套用 Parquet 目录扫描逻辑。[Iceberg 规范](https://iceberg.apache.org/spec/)、[Delta protocol](https://github.com/delta-io/delta/blob/master/PROTOCOL.md)、[Delta deletion vectors](https://docs.delta.io/delta-deletion-vectors/)、[Hudi 表与查询类型](https://hudi.apache.org/docs/next/table_types/)、[Lance table format](https://lance.org/format/table/)

## 5. 各生态的边界与官方依据

下列资料均于 **2026-10-17** 核验。`latest`、`main`、`master` 和 `next` 链接可能继续变化；落地时需要固定规范版本、实现版本和测试样例。规范存在某项能力，不代表某个库版本已经实现，也不代表 GuraDB 已完成适配。

| 对象 | 官方事实与需限定的范围 | 官方参考 |
| --- | --- | --- |
| Iceberg | 表元数据组织文件与快照；v1–v3 与开发中的 v4 需区分。REST Catalog 是独立协议，不能由“文件可读”推导 Catalog 可用 | [表规范](https://iceberg.apache.org/spec/)、[REST Catalog](https://iceberg.apache.org/rest-catalog-spec/) |
| Delta Lake | 以事务日志描述表状态；protocol 与 table features 共同影响客户端兼容；deletion vectors 不能忽略 | [协议](https://github.com/delta-io/delta/blob/master/PROTOCOL.md)、[功能兼容](https://docs.delta.io/versioning/)、[删除向量](https://docs.delta.io/delta-deletion-vectors/) |
| Hudi | 区分 CoW / MoR、snapshot / read-optimized / incremental / CDC；适配需覆盖表元数据与合并语义 | [技术规范](https://hudi.apache.org/learn/tech-specs/)、[表与查询类型](https://hudi.apache.org/docs/next/table_types/) |
| Lance | 文件与表格式均有规范；dataset version、文件版本与 reader flags 分别处理。Blob v2 要求文件格式至少为 2.2，旧 Blob 和混合文件需要专门用例 | [文件规范](https://lance.org/format/file/)、[表规范](https://lance.org/format/table/)、[Blob API 与版本兼容](https://lance.org/guide/blob/) |
| Parquet | 列式文件；page index 为可选元数据，逻辑类型与统计解释影响裁剪正确性。不能据此推导事务或自动支持所有新逻辑类型 | [文件格式](https://parquet.apache.org/docs/file-format/)、[Page Index](https://parquet.apache.org/docs/file-format/pageindex/)、[逻辑类型](https://parquet.apache.org/docs/file-format/types/logicaltypes/) |
| Arrow | 内存列式表示与 IPC；IPC stream 与 file 在随机批次访问、字典规则等方面有差别。应列出实际支持的数据类型、扩展类型与 IPC 元数据版本 | [Columnar Format / IPC](https://arrow.apache.org/docs/format/Columnar.html) |
| WebDataset | TAR 内共享样本 basename 的成员组成样本，多个 shard 用于规模化顺序读取；不是带事务和 schema 演进的表格式 | [项目格式说明](https://github.com/webdataset/webdataset/blob/main/README.md)、[Hub WebDataset 指南](https://huggingface.co/docs/hub/main/datasets-webdataset) |
| Hugging Face | `datasets` 可加载多种底层数据；streaming 是访问模式，过滤与投影取决于底层格式及 reader。Hub revision、config、split、features 都需要保留 | [加载](https://huggingface.co/docs/datasets/en/loading)、[Streaming](https://huggingface.co/docs/datasets/en/stream)、[Hub streaming](https://huggingface.co/docs/hub/datasets-streaming) |
| Zarr | 面向 N 维 typed array，chunk 与 codec 参与存储解释；v2 / v3、扩展、sharding 与 codec 子集需要独立列明 | [规范索引](https://zarr-specs.readthedocs.io/)、[v3 core](https://zarr-specs.readthedocs.io/en/latest/v3/core/index.html) |
| HDF5 | 数据集有 shape、datatype、layout 与 filter；chunk、VDS、外部链接、SWMR 等不是同一项能力。静态文件读取与并发修改读取应分别设计 | [Datasets](https://support.hdfgroup.org/documentation/hdf5/latest/_h5_d__u_g.html)、[高级主题 / VDS / SWMR](https://support.hdfgroup.org/documentation/hdf5-docs/advanced_topics_list.html) |
| MDS | Mosaic Data Shard 使用 shard 与 index.json 描述样本和字段编码；格式访问与 StreamingDataset 的缓存、采样、恢复行为需分别认证 | [Dataset Format](https://docs.mosaicml.com/projects/streaming/en/latest/preparing_datasets/dataset_format.html)、[转换指南](https://docs.mosaicml.com/projects/streaming/en/stable/preparing_datasets/basic_dataset_conversion.html) |
| TFRecord | 二进制 record 序列容器，`tf.train.Example` 是一种可放入其中的消息结构；不能将所有 TFRecord 都按 Example 解释 | [TFRecord 与 Example](https://www.tensorflow.org/tutorials/load_data/tfrecord) |
| LeRobotDataset | v3 组合 Parquet、视频与 episode 元数据，多个 episode 可共享文件；不能依靠文件名恢复 episode。目录细节与变体以固定版本实测为准 | [v3 格式](https://huggingface.co/docs/lerobot/lerobot-dataset-v3)、[Dataset API](https://huggingface.co/docs/lerobot/main/api/datasets) |
| 图片 / 音频 / 视频 | 原始对象保留和媒体解码分开认证；图片格式、音频 codec、视频 container / codec 是不同维度。例如 MP4 容器可读不能代表其中所有 codec 可解码 | [W3C PNG](https://www.w3.org/TR/png-3/)、[Xiph FLAC](https://xiph.org/flac/format.html)、[FFmpeg 格式文档](https://ffmpeg.org/ffmpeg-formats.html) |
| safetensors | 用于张量序列化，可读取张量名称、dtype、shape 与偏移等元数据；主要纳入模型权重资产管理边界，不作为通用数据湖表格式 | [格式说明](https://huggingface.co/docs/safetensors/en/index)、[元数据读取](https://huggingface.co/docs/safetensors/metadata_parsing) |

## 6. Catalog、存储与查询适配接口

下面是完整目标的职责分解，不代表均已实现；当前使用显式元数据定位、受限 reader 与完整对象读取，不具备 REST Catalog、通用范围读取或媒体解码能力。

1. **Catalog adapter**：发现 namespace / table，取得表身份、元数据位置与授权上下文。先评估 Iceberg REST Catalog；其他 Catalog 作为独立连接器扩展。
2. **Table adapter**：协商格式版本与必需特性，解析已提交快照，生成可读文件 / 删除信息与 schema 的固定计划。
3. **File / sample adapter**：解析文件、chunk 或训练样本；报告可安全下推的谓词与未处理的剩余谓词，不伪造“已下推”。
4. **Object access**：统一范围读取、重试、对象身份、缓存与访问凭证；存储后端和 Catalog 的兼容项独立登记。
5. **Multimodal resolver**：把内部资产 ID 或外部引用解析为固定对象、媒体片段 / 数组切片，并关联派生文本、embedding 和 Graph 实体。

需要保留逻辑样本 ID 与源物理位置的映射。全文、向量、Graph 索引都应声明来源表身份、源快照、schema 指纹、对象版本、提取 / 分块规则与模型版本。湖格式连接器只负责正确读取，并不自动提供这三类检索能力。

身份唯一性、无稳定键的快照内身份及跨表版本集合遵循[数据与查询契约](../product/data-contracts.md)。当前触发增量仅接受已验证稳定键的 Iceberg append-only 历史链，更新、删除、压实等非 append 变化明确拒绝；没有配置式自动回退。操作者可另行请求受现有 reader 白名单约束的 Snapshot 重建，不将文件增减解释为通用 CDC。

## 7. 外部变更、索引刷新与权限

当前已实现“固定快照读取 + 显式刷新 + 已发布视图”的有界闭环。下面是继续扩展时须满足的设计约束，包含尚未实现的更新/删除、行列策略和 `data_committed`；它们不扩大页首白名单，事件通知与持续增量同步仍待实现：

- **外部变更**：刷新时解析并固定源版本，默认查询只绑定已发布 read view 内的源版本，不重新解析源最新。显式 `data_committed` 也须固定目标并校验覆盖，不能无意混合提交。无事务格式要绑定对象清单；仅列目录不构成原子快照。
- **索引新鲜度**：记录 `source_version` 与 `indexed_version`。候选策略包括等待刷新、回退扫描或明确请求旧快照；不能让旧索引结果悄悄冒充新快照结果。多源查询不预设跨源原子快照。
- **删除与更新**：源端逻辑删除必须影响结果过滤、索引条目、缓存和派生对象的可见性。源数据物理清理与 GuraDB 派生资产清理是两条生命周期，需明确拥有者、保留策略、引用计数与失败重试。
- **历史与压缩**：外部 vacuum / snapshot expiration / compaction 可能使计划失效；重试/重规划仅可保持同一源版本及对象集合，历史缺失时返回可诊断错误，不能切换最新或返回部分成功结果。依赖 row position / address 的索引需随压缩重新映射或重建。
- **权限传播**：连接器身份、用户访问权限、行列策略和对象访问范围需贯通 SQL、HTTP、后续 MCP / CLI。缓存与搜索索引也必须遵守对应权限；凭证不得写入数据清单、日志或索引元数据。
- **引用稳定性**：媒体引用记录不可变 key/对象版本和内容摘要；摘要只能校验，不能保留被覆盖或删除的字节。不把短期签名 URL 当成长期资产身份。原始对象与转录、缩略图、embedding 等派生数据需有可追踪的血缘。
- **保留与 GC**：数据集登记 `upstream-protected / managed-copy / best-effort`，本地 pin 不约束外部 vacuum。完整托管必须复制媒体、元数据/删除信息与必要特征的依赖闭包；部分列副本仍依赖源。托管 GC 先原子标记 `retiring` 拒绝新 pin，等待既有 query/train/build pin、保留期及安全期，再通过格式维护协议清理。不得直接删除源元数据仍引用的对象；`best-effort` 不承诺长期复现，详见[技术架构](../architecture.md)。

## 8. 后续兼容验收模板

新增连接器或扩大现有白名单前至少补齐以下证据，并分别登记实验范围、已验证子集和剩余缺口。已有受限 reader/导出的依据见页首；不能把它们扩写为完整格式认证。

| 维度 | 需要补充的内容 |
| --- | --- |
| 范围 | 规范 / 实现版本、必需特性、读写方向、后端、Catalog、类型与 codec 白名单 |
| 正确性 | 固定快照与 schema；NULL / 嵌套类型 / 时间与精度；删除、更新、schema 演进与非法输入 |
| 互操作 | 外部官方实现生成 fixture，GuraDB 读取；有导出能力后再做外部实现反向读取 |
| 查询 | 投影、谓词下推与剩余过滤结果一致；全文 / 向量 / Graph 组合检索遵守源快照与权限 |
| 训练 | 大对象按需读取、分片并行、固定 seed、worker 分配、训练 checkpoint 后恢复及样本覆盖语义 |
| 生命周期 | 外部提交、压缩、删除、过期与权限撤销下的索引和缓存行为 |
| 规模 | 冷 / 热缓存、对象请求量、扫描吞吐、随机访问延迟、并发读取及失败恢复 |

## 9. 待讨论的问题

- 首条工作负载及 M0–M4 按[路线图](../roadmap.md)推进；后续具身智能与科学数组的样本模型需独立设计。
- 外部源保持只读，导出与外部原地提交各自验收；后续有哪些业务确需原地写回？
- 外部引用与托管对象可共存，但保留等级和删除拥有者必须登记；哪些源能提供可执行的 upstream 保护协议？
- 源端高频变更时，检索的新鲜度、训练可复现性和索引维护成本如何权衡？
- 是否开放第三方连接器接口，以及扩展类型、字段约定、媒体解码和数据集布局的认证流程？
