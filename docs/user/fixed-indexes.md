# 固定 BM25 / 精确向量物理产物开发验证

状态：**恢复树原始范围的首次完整 INITIAL 9 套门禁与三项真实组件 driver 已通过，两轮独立复核 PASS；最终提交和集成验收待完成**。结果绑定文末的运行前24文件冻结，不代表本次文档更新后的最终head已验收。已验证真实单文件BM25/精确向量产物、独立重开和真值对照；本页供模块开发者使用，不新增数据库查询/构建服务入口。hook/提交后检查、PR/主线及真实I1仍待完成。

## 场景与操作

目标是从固定合成事实/处理输入构建两个单文件派生产物，关闭builder，在新reader中经实际ObjectReadPort重开，返回A CandidateBatch，再由独立Parquet reader回查全部身份/版本/坐标及候选。测试driver使用可信fixture locator，**不从batch ordinal推导physical位置**。

前提：Python3.11+、仓库锁定依赖、已固定P01 synthetic fixture（manifest SHA-256 `455fc7a3e8c75a1c5446ecc52a3ead105f930607957f8f10eaaca8ffb1d32f94`）。无需PG/云凭据或服务。本机组件入口如下，每次必须使用新的output目录，已有目录明确拒绝：

```sh
.venv/bin/python scripts/fixed_indexes_acceptance.py --mode functional --output artifacts/fixed-indexes/functional
# 性能/故障只在协调者分配的独占窗口执行
.venv/bin/python scripts/fixed_indexes_acceptance.py --mode performance --output artifacts/fixed-indexes/performance
.venv/bin/python scripts/fixed_indexes_acceptance.py --mode fault --output artifacts/fixed-indexes/fault
```

功能命令产出真实封存文件、canonical描述符、独立回表/排名/分数差异报告及输入/配置/代码摘要。旧树19项单元、Python全量223项和3808/3808执行行（missing0/excluded0）、functional/performance/fault三项真实driver已有本地通过记录。旧三driver对应当时21文件冻结 `077d94dd449a46f188439b86ba13be6a941815fea09e0d1419115687f4549a3c`；独立复核核对11条事实、10向量+1显式NULL、三个Parquet row group、8组查询与重复读取及13项拒绝，分数误差为0。它们保留为历史结果，恢复树的全新INITIAL和三个新报告见文末。精确命令、报告SHA和边界见[变更计划](../design/fixed-indexes-change-plan.md)、[场景表](../design/fixed-indexes-scenarios.md)。

旧轮为本机Python3.14单版本、synthetic小规模与已有依赖/OS缓存环境；新reader子进程没有应用内容缓存，但未清除OS缓存。性能通过仅对应原5秒build、1秒query、512MiB与1MiB文件预算，不是冷环境基线或业务质量结论。旧报告不替代恢复树Rust/完整harness或本次文档更新后的checkout验证；真实P03/P04/B-L/PG配对及I1仍待完成。

## 支持与拒绝合同

- 单source snapshot；每artifact单文件、shard_count=1；最多100条事实/1MiB私有文件；BM25-flat与3维exact_vector，无delete/增量/ANN/Graph。
- BM25消费固定人工tokens，k1=1.2/b=.75；NULL/空文档计入N；过滤后不重算统计；保留重复query term贡献。查询UTF-8词按固定空白表切分，不做大小写/Unicode归一化，不认证通用中文分词。
- vector消费完整独立processing/null mask，每个可见ID/version明确present或null；缺条目、错模型/维数/处理版本不是NULL。无真实encoder/模型质量声明。
- 候选采用A finite binary64 hex、squared_l2非负升序/BM25降序、同分按ID，返回route top_k窗口；candidate_limit不截扫描输入。白名单用集合交集，未知ID不命中，context/tenant/模型错仍拒绝。
- 固定输入、配置、完整coverage/mapping、ObjectRef版本/size/SHA均核对；坏文件/短读/未知字段或格式、重复ID、旧locator、缺成员拒绝。不得从P01参考posting/golden直接返回候选。

## 权限、预算与恢复

入口接收固定A binding/query与注入的当前授权/取消/计量scope；每次请求及输出前检查。fake目录/对象registry仅为module测试信任，不能替代真实授权。所有读取、校验、重试、解码、扫描、输出与构建成本计量；超限/取消/deadline失败，不返回partial complete=true。

失败case不返回complete成功，不等于整个scope没有花费。故障driver的guarded scope在撤权/取消注入前完成过一次成功读取，累计output_bytes为2284；后续失败不能抹去既有费用。对象调用失败前按预期ObjectRef大小保守预扣预算，此数值不能当成短读/缺失故障的实际wire传输量；真实P03后端字节、重试与父scope总账配对仍pending。

scope以原TTL和wall余量固定单调时钟期限，后续仅缩短；授权和最终取消回调均返回后，再读取新鲜wall/mono并校验期限，最终时钟校验之后不再调用授权或取消回调。即使取消回调耗尽期限却返回False也拒绝成功，墙钟冻结/回拨不延长执行。driver要求仓库内新输出目录，拒绝复用；前后源码/commit/锁、环境、真实源与索引字节摘要必须一致绑定，异常仍保存失败证据。物理Parquet字段的ID/type/nullability独立核对，不以resource role字段表代替真实源schema。

只写可信调用方指定的新构建目录；已有目标冲突，不覆盖旧artifact。文件create-once/fsync成功且全部验证后才返回描述符；失败保留现场，不发布目录指针。没有源提交或外部发布副作用；恢复使用新build目标，不删除失败记录。

源ObjectRef/metadata/snapshot改变必须新SourceVersion/DataRevision，即使逻辑内容不变。显式record_version可保留；revision_version映射随新revision改变。只重建派生索引、源不变可同revision新artifact/view。

新revision属于source/catalog的不可变登记前提；当前P06没有跨历史目录状态，只验证当前固定引用与完整输入。构建必须读取合法已发布、受保护的scan-only/索引view；未发布ingest revision的BuildContext/operation pin合同仍待后批，不能伪造查询上下文或借legacy旁路。

私有格式有独立format_id/version，旧reader不支持时拒绝；不修改旧alpha索引/reader/发布/Job/pin，也不改变A。source locator仍trusted fixture；P04/B-L、真实P03/PG/P05/P10接线与I1另验收。本机文件/模拟环境不认证真实云、多机、按需规模、倒排seek性能或产品baseline。

## 恢复树首次完整检查的实际结果

2026-10-21 在 `codex/p06-fixed-indexes-recovery`，以原任务base `4d6baca888421d90f146679ef71b0e555fe60881`、HEAD `17d66c66a067eebe73280ce8d3488fb4f7cdcfe9` 运行全新INITIAL。运行前24文件清单SHA-256为 `ca86467e9557eadbc08f597442518fb3db70c43720f0babf8a0c933ee9dda27d`，检查和三个driver前后均一致。9套门禁、26条命令全部PASS；全量Python225项测试通过，3808/3808适用行、missing0/excluded0；Rust按lcov唯一源码行计，原始3344行、覆盖3323行，保留原15组21行排除，适用3323/3323、missing0。Rust测试与采集在unit-coverage中执行，不额外宣称未选中的独立Rust suite通过。

本轮报告根为恢复树 `artifacts/harness/20261021T062755Z-98f8d0e9/`；总 `report.json` SHA-256为 `d1c849e602e32eb5792010154fa043b7f9d05836e7234743eb99770d25ed5845`。其中 `fixed-indexes-functional`、`fixed-indexes-performance`、`fixed-indexes-fault` 均为独立新输出目录，三个 `report.json` SHA依次为 `399b4004009dc8024c2838e1b5d2a480dffb8ede3b590c7d76a747bb001f4b1f`、`8885813437c054fb9ca436eab902801a82d69b1966fd3ffb4f25e3e146810c81`、`67030a41539b13015e1078d2e71c15dcd2eac193ede59a1bb6a70c6e09caa580`。

两个正常driver均独立核全部11行、10向量+1显式NULL、3个物理row group及8组查询/重复读取，P01真值与分数差异为0，原build/query/内存/文件预算通过；13项故障均按预期拒绝且该case未返回complete。P01作者外源码/数学/定位及小型raw复核SHA为 `3d7b0be0f6f784ebeace2ee8ab4bd119a2405d8f3650b0a2d6d963cd62187b3b`；plan_audit作者外全源/26条命令/全部raw与profile复核SHA为 `5d9c8e05391efc665fe425f7c145c159b0d2ab13af03a815a80c0c0c1643da22`，均PASS；精确路径见[变更计划](../design/fixed-indexes-change-plan.md#恢复树-initial-全新证据与独立复核)。

这仍是本机可信locator/processing fixture组件，OS缓存未清除，没有真实P03/P04/B-L/PG/P05/P10配对或I1证明。旧driver和失败记录保留原义；此次只更新三份结果文档，最终head/hook/提交后原base检查、task-finish与长期raw归档、PR双CI/精确main验收仍pending，不以INITIAL通过替代最终交付。
