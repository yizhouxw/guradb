# PG 数据块直接写入：独立需求与原型合同

核验日期：2026-10-21。研究仅使用官方网页/源码文档；本文是需求与原型的先行合同，尚无本项目物理导入通过证据。对应[需求矩阵 B01–B05](../product/requirements-v2.md)与[模块 owner](../design/module-delivery-contracts.md)。Lakebase 物理 bulk、Neon 页/WAL 协议与 stock PG 分别认证。

## 已核实事实

| 主源 / 日期与范围 | 可支持的事实 | 不能从它推出的结论 |
| --- | --- | --- |
| R1 [Databricks工程文章](https://www.databricks.com/blog/load-terabytes-data-minutes-lakebase-postgres)，发布2026-10-08 | Spark workers在隔离PG sandbox生成可读heap与索引产物，目标catalog OID协调、冻结tuple、page checksum；上传后manifest/目标SQL调用，以compact WAL及原子swap发布。该路径围绕extension/table AM，不是所有行流经在线primary的COPY。 | 未公布可供任意第三方使用的稳定物理导入API、extension/AM版本、完整build兼容表；不能凭文章将任何PG18数据目录当写入目标。文中性能是供应商特定负载，heap构建测量不等于全索引/系统成本，不采纳其倍数为本项目SLO。 |
| R2 [AWS Synced Tables文档](https://docs.databricks.com/aws/en/oltp/projects/sync-tables#accelerated-sync-with-ltap-direct-writes)，更新2026-10-16 | LTAP Direct Writes为可选Beta、Synced Tables为GA；Lakebase PG16/17/18，创建时选，现有表不能直接追加开关；初始加载各模式可用，Snapshot后续全量也用，Triggered/Continuous后续变化走CDF。 | 不推广到所有云/所有PG发行版；major支持列表不证明16/17/18页格式互通。源Delta/Iceberg同步、Direct Writes和普通PG客户端是不同能力。 |
| R3 [Lakebase架构](https://docs.databricks.com/aws/en/oltp/projects/architecture)，更新2026-07-27 | compute把WAL交给safekeeper quorum，pageserver按LSN重建页，对象存储留历史；正常事务提交不等数据页最终物化。 | GuraDB的控制PG不因此成为该分布式存储；不能绕过目标自身提交协议或把对象PUT成功称PG事务成功。 |
| R4 [Neon架构](https://neon.com/docs/introduction/architecture-overview)，页面日期未明确，2026-10-21核 | 区分compute执行/cache、safekeeper WAL持久性、pageserver页版本/redo与对象存储。 | 这说明分离架构，不证明开放“第三方任意live写页”的服务合同；未核Neon具体PG major/commit或Lakebase私有物理导入扩展的可用性。 |
| R5 [Neon官方pageserver文档](https://github.com/neondatabase/neon/blob/main/docs/pageserver-services.md) / [raw](https://raw.githubusercontent.com/neondatabase/neon/main/docs/pageserver-services.md)，main未钉commit，包含历史实现描述 | Page Service收GetPage@LSN，客户端是compute PG，借libpq协议传输；WAL receiver物理流复制并重建页。 | libpq传输不等于普通SQL SELECT或COPY接口；历史main文档不是现行生产版本认证，不将其sharding/TODO或线程描述当最新事实。 |
| R6 [PG18升级](https://www.postgresql.org/docs/18/upgrading.html)，2026-10-21核固定/18路径 | minor内物理存储兼容；major内部格式可能变化，需要受支持迁移路径。 | 不推定同major即可任意跨fork/extension/arch写页，也不推定跨major二进制可互读。 |
| R7 [PG18物理页布局](https://www.postgresql.org/docs/18/storage-page-layout.html) / [COPY](https://www.postgresql.org/docs/18/sql-copy.html)，2026-10-21核 | 页大小可编译选择；tuple解释依赖catalog/NULL/alignment/TOAST，索引有自身metadata；COPY FREEZE有严格新表/快照前提。 | page header版本相同不是完整物理兼容证明；不能在live target直接FREEZE/替文件模拟安全bulk发布。 |

R1文章声称其导入实现不改PG core，使用extension/table AM；这不是对整个Lakebase/Neon体系“无fork”的证明。本稿没有查到该物理导入扩展的公开版本化API或开源构建产物，必须列为原型前阻断；两条Neon版本兼容页未可取，本稿不猜其支持major列表。

## 需独立立项的候选，不相互替代

| 需求ID | 目标 / 最小验证物 | owner分责与停止条件 |
| --- | --- | --- |
| B01-L / B02 / B03 | Lakebase式离线并行构建原生heap/index→storage ingest→target原子发布；首先确认可获得/可本机运行的目标扩展和protocol | connectors拥有目标格式builder/ingest与原生receipt；storage仅不可变字节/校验；目标PG拥有本身提交点；Gura catalog只发布自己的revision/view。没有可用目标接口则保持blocked，不能换普通COPY宣布同需求通过。 |
| B01-N / B04 | Neon compute→WAL safekeeper→pageserver、固定LSN读取/恢复或受控离线timeline/basebackup导入的研究 | storage适配与connectors边界由架构师先定；需pin repo commit/PG fork/网络协议/工具。当前主源只证明架构机制，不确认导入命令/API。不可据GetPage read设计第三方live写入。 |
| B01-G | GuraDB既定湖架构内后台构建Parquet/派生索引，再按源协议提交并发布 | 这是原I07/S05的原生Gura路径，可继续服务I1–I3；不冒充PG物理兼容。若选择新增PG物理后端/目标，需ADR明确它服务哪种用户场景、权威与运维成本，不能把业务数据塞入小PG控制面。 |
| I-PG-LOGICAL（另P1） | 普通PG逻辑批量导入/导出及wire/COPY客户端兼容 | 可作为独立功能或基准对照，但不是以上任何物理需求的替代验收。 |

## 物理兼容矩阵必须冻结的输入

本项目建议先一个精确PG major+minor/build digest、一个CPU/OS和一个target extension/table AM版本。不承诺任意16/17/18；再逐组合扩展。每个组合记录supported/rejected/pending，而不是“兼容Postgres”。

| 维度 | builder / target共同责任 | 正负原型证据 |
| --- | --- | --- |
| 身份/catalog | database/schema/relation/type/attribute OID、逻辑schema/fieldID映射、目标权限与schema generation；OID分配与并发冲突处理；CTID只作物理地址，不能替代Gura稳定ID/version | 非连续ID、相同投影不同ID、目标schema改变、OID碰撞/错映射拒绝 |
| 物理编码 | page/block大小、页checksum规则/位置、relation/fork/segment引用、tuple alignment/NULL位、varlena/TOAST及compression、字节序/ABI；索引AM/opclass/collation版本/ctid重定位 | min/maxint8、bool/NULL、UTF8/空串、足够长text触发TOAST；坏checksum/漏TOAST/mismatchedbuild前置拒绝 |
| 可见性 | 仅隔离sandbox生成；目标own commit与snapshot隔离；XID/frozen tuple/可见性元数据与constraint/unique验证；不能把sandbox事务历史带进live target | 原snapshot在publish前不见staged数据，commit后新snapshot见完整集合；重复key/索引heap不一致不能发布 |
| 持久性/恢复 | 不可变input manifest+全依赖摘要、target原生operation/fingerprint与receipt、authoritative认领点；提交unknown先对账、旧attempt fencing、PITR所需对象和WAL保留闭包 | 上传/目标认领/commit前后崩溃与丢响应；重放不重复、生效不丢、坏页不权威、恢复不漏已确认行；不能凭对象存在猜commit |
| 清理与授权 | Gura和target分别检查owner/pin/保留；未发布产物与已提交引用分开；业务撤权与物理GC不同 | late old manifest拒绝，合法pin/target仍引用拒绝删，失败清理不抹掉primary未知事实 |

上述是本项目候选验证义务，不声称Databricks/Neon已公开每项内部做法。目标必须自己证明哪种metadata/extension才让页成为权威；GuraDB不能私自写其live数据目录或伪造compact WAL。

## 最小可证伪原型计划（当前均未执行）

1. **R0可行性准入**：架构owner确认精确目标与用户方向，拿到可本机运行/许可允许的protocol/extension/build；固定源数据、catalog快照、page格式版本。无法获得则交付缺口+成本/替代路线的决策材料，B01-L不标完成。先不加线上API/不迁业务数据。
2. **R1格式读回**：只有一个受控本机target，非live文件手工替换；用真实目标执行生成/接收功能。固定P01全11事实（两来源义务保留）+8192独立perf样本；独立PG查询/源值核int8/NULL/Unicode/大text、heap/index同值与逻辑ID映射。若只能COPY到primary，结果记I-PG-LOGICAL，不记B02。
3. **R2提交与恢复**：在真实原生认领/commit点前后注入崩溃、网络丢返回、重复/迟到op、坏slice/目标schema变化；记录before/after原生状态与receipt。恢复后既不半表/漏行，也不误回收已确认产物；证明失败/取消已有副作用的对账边界。
4. **R3真实成本**：同输入schema、索引、持久性、冷热定义与固定环境，对比逻辑COPY与物理导入的生成、上传、校验、主提交、query-ready全时段；至少记rows/s、bytes/s、WAL/对象请求bytes、builder/primary/target存储CPU/RSS/临时盘、索引构建和查询干扰。先冻结数字预算再测；不只计heap或省略预热/索引。当前目标数值**待冻结**。
5. **R4正式收口**：只给该固定组合supported，异major/fork/AM/ABI/源特性逐项拒绝；随后才讨论并行worker/增量/升级窗口。真实云/多机证据仍按既有规则pending，只能先本机模拟。

跟踪原需求矩阵B01–B05；R0/R1可由一个研究owner短片交付，不阻塞既定对象湖I1。产品经理不能把供应商仅beta的特性/非公开extension变成默认实施依赖。

## 本轮最小本机原型（先行合同与原语实测）

p01 准备固定 PG18 镜像的隔离原语实验，ROOT 独立审查后授予执行窗。记录真实 build、blocksize、checksum、encoding/collation、catalog/type OID、heap/TOAST/B-tree 及所有 11 个 P01 成员、int8 极值、NULL、Unicode/大 text 的读回。仅在合规新表事务用 COPY FREEZE，反例核非新表/跨事务限制、重复 key 原子拒绝。pageinspect 若不可用则记 missing，不拉未知扩展、不手改 live files、不伪造 WAL。此实验只给格式生成原语证据，不实现 Lakebase storage-ingest/Neon 写页；目标原生 API 仍是独立准入条件。原型未执行前 M/P/S 一律 pending。


2026-10-21 13:47 UTC追加实测：固定官方PG镜像digest `afc7e2d…`，实际PG18.6 Debian/aarch64、8192B block/checksums on/UTF8/C。完整11个P01事实加1个显式TOAST探针，顺序/索引读回与独立expected一致；3个B-tree和真实TOAST关系；非新表FREEZE、跨事务FREEZE、重复key原子拒绝分别返回55000/55000/23505，失败后原12行与拒绝状态不变。34条真实命令、外层exit0/3.713721s，所有进程组与owned容器/匿名卷已核清理。SOURCE runner `00686fe9…`；实际报告 `d4221851…`，ROOT独立核全部日志/输入/输出/资源的记录 `049cbb9838b9ddc82f4c41d644e43f3ea4b26cd6a69d8d9199bf8f01b3f1956e`。原件位于本机 `artifacts/strategy-v2-product/pg-primitives-candidate-v2/`，不提交运行产物。

此结果只证明stock PG格式生成/读回及三个拒绝原语，**B02/B03/B04物理目标、跨build兼容、吞吐与恢复仍未验证**。pageinspect只使用镜像已有扩展；实际页header checksum=0、computed=-2816分别记录，未声称磁盘页checksum相等或损坏认证。首次只读预检exit2/0.151410s因Docker Desktop的tag@digest解析拒绝，未创建容器/执行SQL；保留失败，只改同一digest的canonical repository@digest引用后进行上述独立新尝试，无pull或宽松fallback。3.714s不是数据导入吞吐或产品SLO。
