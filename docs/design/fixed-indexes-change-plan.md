# P06 固定物理索引变更计划

状态：恢复树24文件冻结下首次完整INITIAL9套门禁/26条命令、Python3808行严格覆盖、Rust3323行适用覆盖及三个新driver全部PASS；源码/算法/定位与全部raw/profile两轮独立复核PASS，最新证据见文末。此次仅更新结果文档，不把结果挪作最终head/hook/提交/CI/main或I1验收。旧树历史身份：worktree `/Users/chad/dev/guradb-p06-fixed-indexes`；branch `codex/p06-fixed-indexes`；原始base `4d6baca888421d90f146679ef71b0e555fe60881`，起始树干净。task `p06-fixed-indexes` / `5d6c4767f9ca48f3b7f70755e0f6f258`；checkpoint `checkpoints/20261021T015513Z-before-p06-fixed-indexes-7a968bab`。

## 目标、归属与风险

遵循ADR0004/0007/0016/0018/0020、[A合同](../interfaces/cf1a-contract.md)、[数据合同](../product/data-contracts.md)。从可信固定输入真实构建、fsync封存、销毁builder、独立重开并按A ArtifactReadPort读候选；独立PyArrow回表与P01 oracle核对全部ledger和算法真值。模块证明不代替真实P04/B-L/P03/PG/I1。

独占新增 `modules/index/fixed_{artifacts,layout,bm25,vectors,candidates}.py`（必要同prefix拆分≤600行）、`tests/unit/test_fixed_indexes*.py`、`tests/index_support/`专用子文件、`scripts/fixed_indexes_acceptance.py`及本任务三份文档。禁止修改旧索引/common/P01truth/locks/harness/根README/plans；共享手册导航/driver policy/组合根由root后续接线。index只依赖common/storage，不导入catalog/query/connectors/cluster；不新增依赖。

风险涉及INV-001稳定身份/版本、INV-002固定视图/索引覆盖、INV-003缺口拒绝、INV-004发布权分离、INV-007预算取消/撤权、INV-009真值与质量。初始plan影响index与反向消费者；required_suites以实际harness plan为准，保存 artifacts/fixed-indexes/initial-plan.json。新生产行严格100%覆盖，不增豁免/改阈值。

## 冻结的有限输入与物理格式

上限：单source、最多100条source record、dimension=3、每条最多1024tokens/每token最多128字符、最多4096词项、单artifact≤1MiB、单shard，无delete/增量/ANN/Graph。读请求仍遵守A≤30s及全部原预算，未实现scope/依赖拒绝，不取latest。所有动态数据/列表/解码都有上限。

私有format `p06-bm25-flat` v1与`p06-exact-vector-flat` v1；不加common payload/capability，A reader_capabilities仍精确`['fixed_read']`。strict canonical UTF-8 JSON：固定ASCII字段、无JSONfloat、未知/缺/重复字段、unsafe integer、bool冒数字、非有限hex均拒绝。词项用有序(term,tf/df)数组，避免动态Unicode字段名排序歧义。

文件内容为header、configuration、rows、statistics及configuration/mapping/coverage摘要；header绑定artifact/build、revision/schema/source、完整processing输入manifest SHA和模型/处理版本/计数。配置SHA对configuration对象；mapping SHA对按ID排序的完整ID/version/RowLocator数组；coverage SHA对完整身份/资格/值ledger；各自不含自身摘要。文件SHA/size封存后只放外部IndexArtifact.shards，不把最终文件hash再嵌入文件形成自引用。artifact/build ID由可信调用者预分配，不从包含自身ID的文件hash反推。

完整processing manifest独立覆盖所有可见record：明确text present/empty/null、tokens及vector present/null/reason/hex，并绑定dataset/revision ID、schema/source、model/处理配置和真实固定源ObjectRef；present还逐项绑定feature ID/version、parent ID/version与模型/处理空间。fixture独立列出全部11条processing mask，present缺feature或null却有feature均拒绝。其固定引用属于fixture revision依赖闭包；**不包含后生成的binding/batch摘要造成自引用**。A批次在完整binding生成后验证，locator由独立真实Parquet枚举，逐ID/version匹配，生产builder不导入P01/硬编码null ID。任何缺entry失败，不以缺条目推NULL。

BM25配置：model_id=`bm25-fixed-tokens`/version=`1`、dimension1、metric=bm25、analyzer=`fixed-whitespace-v1`、processing=`zh-CN-hand-segmented-v1`、k1/b用binary64 hex。固定分隔符表为U+0009–000D、0020、0085、00A0、1680、2000–200A、2028、2029、202F、205F、3000；空白后零token拒绝，重复term逐次加分；大小写/Unicode不归一化。N包含NULL/空文档、全source统计后过滤，无match不返回。空域/avgdl=0不除零。

vector配置：model_id=`outline-synthetic-zh-image3`/version=`1`、dimension3、metric=squared_l2、analyzer=none、normalization=none、processing=`zh-CN-hand-segmented-v1`。原始/请求分量均finite且绝对值≤1e150，bool拒绝，按固定维度次序`math.fsum`累加平方差并验证finite/非负；明确NULL不填零。配置包含所有影响打分/eligibility的规则，reader重算匹配binding的artifact/requirement及IndexQuery共享字段。IndexQuery没有format字段，格式从artifact选reader。

输出完整A CandidateBatch，context/query摘要均为对应完整Contract envelope SHA。输出前跑common semantic helper；len≤route top_k，candidate_limit限制保留容量、不截扫描域。filter ids语义是与完整coverage域求交集，空/未知ID无hit；跨scope仍拒绝。纯分数比较只在精确相等时按ID；P01容差不能用于重定义tie。物理文件坏内容为corrupt_object；请求/能力/预算/取消等沿A错误，不泄漏legacy Failure枚举。

## 构建、读与恢复

builder仅向新可信本机构建目录create-once写盘、flush/fsync文件和父目录，已有目标conflict；只有全部封存后返回IndexArtifact。失败保留目录/日志，无ready/published回执。源内容不变的索引重建可同revision；源physical object/metadata/snapshot变化即新revision，record_version依显式/派生策略处理。

新revision要求由source/catalog不可变登记保证；P06只持有当前固定binding，无法独立证明跨历史ID未被复用。此片验证旧ObjectRef/hash和manifest固定、不重绑定latest，不宣称已证明PG跨历史不可变约束。合法构建输入来自已发布且受保护scan-only/索引view；未发布ingest revision不得伪造QueryContext，后批BuildContext/operation pin仍pending。

reader经注入ObjectReadPort取完整文件并核对固定identity/size/SHA/格式/header/配置/ledger；不缓存授权，首片无应用内容cache。fixture对象registry映射固定key/version→真实封存文件，绝对path只是driver内部实现，不是公共ObjectRef。当前授权/取消/deadline/预算由显式注入scope负责，每次请求及输出前检查，父scope累计所有attempt/batch，不在reader重置。旧索引/PG指针/源提交不变，没有迁移或外部副作用。

build_usage的elapsed覆盖builder函数，输入获取的实际读取另列pipeline计时与registry请求；5秒build预算使用含输入获取的每artifact pipeline时间，不能用函数局部elapsed替代。I/O预算保守扣requested bytes，正常registry请求另存actual/checksum bytes；失败ObjectReadPort调用前的预扣不能冒称短读/缺失故障实际wire字节，P03真实后端累计计量/重试配对仍pending。内存预算使用解码前有界64倍组合输入reservation峰值，真实进程RSS另测。CandidateBatch保留单批delta而父scope累计各次IO/输出，memory_bytes为保守峰值；无已实现的共享P10总账声明。

若失败先保存日志/输入/源码与假设，再定位；两次同因无新证据失败停止盲重跑。需要回退在新目录从checkpoint恢复，禁止reset/clean覆盖现场。私有格式未知version拒绝；旧alpha继续其原入口，不能读新格式就明确报不支持。

## 验证与执行窗口

review-01独立审查要求的修复在源码前记录：R1 scope创建时以原TTL、当前wall余量和单调时钟固定总期限，此后只能缩短；auth回调后重新读取wall/monotonic与取消，冻结/回拨wall不延长30秒，慢auth不可拿调用前时刻通过。R2 source schema与resource roles分开，真实Parquet显式写field ID/type/nullability，source schema指纹和mapping据实际物理字段建立，独立audit读取真实schema核对。R3 driver只接受新输出目录，绑定完整checkout/commit/locks/env、实际输入/产物SHA，异常finally保留报告与日志，运行中源码变化不得绿。修复后的source/tests/driver全指纹重新冻结与独立复核，旧11单测不当当前精确证据。

review-02补正也先记录：最终cancelled回调可能耗时并返回False，故其取值、严格bool和状态检查必须置于最终fresh wall/mono及validate_access/单调期限校验之前；授权/取消回调全部结束后才取最终时刻。新增确定性负例令最终cancel回调推进mono越过deadline却返回False，必须抛deadline，不能返回complete成功。仅调整scope顺序与专用unit，其余五个生产源保持review-02。

1. 当前三份用户/场景/计划在行为源码前落盘，保存 `artifacts/fixed-indexes/docs-first.patch`。共享用户README不编辑，按root owner安排导航。
2. 实现格式/构建/算法/候选及完整mask/ledger与范围拒绝；局部unit执行先获root窗口，不自行运行覆盖/cargo/容器/重型driver。
3. 真实driver functional：P01 manifest固定，生成真实Parquet多rowgroup且物理顺序不同于ID/排名；全source values/int8/NULL/身份/locator/processingmask逐项独立回表；builder结束后子进程重开索引；P01独立排名与score差异，不用生产结果自证。
4. 受控performance：记录新reader/重复reader（OS cache未清除需披露）、文件/事实/必要vector字节、构建/查询时间、GET/bytes/校验/重试/全扫描计数及峰值RSS；新组件绝对预算为每artifact build≤5s、单query≤1s、driver process RSS≤512MiB、文件≤1MiB。仅11条synthetic模块预算，无提速/产品baseline结论，不改任何既有门槛。
5. fault：写盘/封存失败、坏stats/vector/header/ledger/locator、短读/缺对象、取消/撤权/预算、源重排和版本策略、上下文错配。不得返回partial complete=true；真实raw/trace另归档，不能只存harness摘要。
6. 完成实现主动请求独立review；root分配正式完整harness/hook/postcommit原base检查窗口。新driver需root串行接线并实际执行；文件存在不等于suite已纳入。最终commit/checkpoint/task-finish、PR CI/main精确复验另留证。

早期状态：首稿11条unit后，review-01收紧和R1–R3修复阶段曾无当前源码执行证据；该历史结果不能替代下文重新冻结、19项unit及实际覆盖/driver。正式完整门禁、P03/P04/PG/B-L真实配对、I1/ANN/Graph/业务质量仍pending。


## 旧树局部证据与共享接线合同（历史）

root实际读取review-03源码/增量并重算全部16文件，清单 `dc24309b984f3c65766c2fd0953f9af755a5ff36cd8a980b55cf6857f2580167` 匹配；获受控短窗口执行 `python -m unittest discover -s tests/unit -p 'test_fixed_indexes*.py'`，19项0.454s通过、wall0.743266s/exit0，前后16SHA不变。fresh日志为 `artifacts/fixed-indexes/unit-review03-20261021T034740Z/`，stderr SHA `7b4ca9458862308c0b4371ec3bb31aa55cb977d9e090893a7d566b17f51003ef`。仅局部单元，既不证明真实driver也不覆盖新文档/接线checkout。

作者p00明确交回整树后root成为唯一写者；先保存本段与共享用户导航/追踪，再接harness。仅追加现有functional、performance-smoke、stability-component中的fixed_indexes_acceptance functional/performance/fault三真实命令，每次独立新--output目录，Pythoncompile路径补driver与index_support；standalone driver/support代码变化也要求Python/功能/组件成本/组件故障/严格覆盖五门禁，纯Markdown保持文档路径。补防漏选负例；已有命令、timeouts、完整performance/stability/soak的planned状态、strict100%与旧21Rust排除保持。本片无新增依赖或architecture例外，不捎带改已有runtime。

共享接线独立复核后已按受控窗口完成下节Python覆盖与三driver。旧分支的CI预算/覆盖工具基于当前base4d，完整检查须先与前置worker工具修复的已验收主线对齐，保留原base/范围及dirty失败现场；新命令增加的最坏时限需重新核定，不能盲跑已知不闭合旧CI预算或抬产品5秒/1秒/512MiB阈值。提交/PR/精确main与两版本CI仍待完成。共享接线不把bounded文件registry变成P03/P04/PG真实配对或I1。

## 旧树本地组件实际结果与证据绑定（历史）

19项单元对应前述review-03的16文件；shared接线后的21文件冻结为 `077d94dd449a46f188439b86ba13be6a941815fea09e0d1419115687f4549a3c`。该冻结在policy单测、Python覆盖及每项driver前后均完全一致，Git head仍为原4d6baca；没有以提交后的空差异或旧结果补齐新范围。

policy单测1项通过；`scripts/unit_coverage.py --language python`实际执行223项测试、3808/3808行、missing0/excluded0，wall29.448s。原始记录 `artifacts/fixed-indexes/python-first-20261021T040621Z/result.json` SHA `1b2d9b603833e8368ad647ccde4fbb392a425f3218ff0950c9e46507ecae61df`；保留PyIceberg回退纯Python decoder的UserWarning。未运行Rust覆盖或完整harness，不能引用A的Rust结果替代本片检查。

三个driver分别使用新的output目录，无复用计数或报告；raw根为 `artifacts/fixed-indexes/drivers-first-20261021T043251Z/`，精确argv/stdout/stderr/退出码/耗时和前后21SHA位于同目录外层，全部exit0且无stderr：

| mode | wall秒 | report.json SHA-256 |
| --- | ---: | --- |
| functional | 1.890550 | `10f14ffc3f974adb153cae2415868d0dea73cebee899769647b92303feab1ebe` |
| performance | 1.902979 | `658feba8889cff4a16e7f35b579e37cc73ef34cc485ac9f8612b045752ad668e` |
| fault | 0.316537 | `e0706580d52b2a872aa440318db9ffcab434f902f100df4a182ecb5aa6f4d4b5` |

三项driver源码JSON摘要均为 `373846875a6b1f9f636295b0eb10761eac87f4a5419eb1707e8493892fcad9cf`，这是排序源码SHA的JSON算法，与harness包含模式的checkout_digest不同。三项均保存环境/锁、真实Parquet/processing、两个封存artifact及逐文件raw摘要；functional/performance另存binding/query和候选score/locator，fault在report中保留13项trace与失败staging。root作者外独立复核 `/Users/chad/dev/guradb/artifacts/reviews/p06-driver-evidence/review.json` SHA `02575b747fcf00f7d4c6c023be70ed72bc238676f0cccd4b00a3b8dbd2dc8c12`：全部11行/10向量+1显式NULL、3个row group、实际物理field ID101–106及resource1–6映射、每正常driver8组查询/重复读取/独立P01真值均匹配，最大分数误差0；13项fault均拒绝且不发complete输出。

performance每artifact含输入获取的pipeline为5.901ms/5.522ms；8组新reader查询为7.554–8.403ms，重复查询为7.316–8.579ms，两个封存文件12649/12612bytes，原5s-build/1s-query/512MiB/文件1MiB预算均满足。本轮为已有依赖和OS缓存的本机Python3.14环境，新子进程不持有builder或应用内容cache，OS缓存未清除；不作为冷环境、生产规模、倒排seek/ANN或业务质量baseline。

本次仅同步三份结果文档，运行代码/测试/driver/共享接线不变；上述通过不精确绑定更新后的checkout。源码备份保留旧版并刷新新manifest，仍不stage/hook/commit/recover。实际raw的共同Git独立归档待最终head，task-finish只自动归档harness报告/日志。完整Rust/harness、提交与双版本PR/精确主线、本机模拟后端/源的真实接线和I1均缺当前证据。


## 原范围源码恢复与共享接线（先行合同）

原dirty树、task5d6及三driver原始证据保留；新 `/Users/chad/dev/guradb-p06-fixed-indexes-recovered`、branch `codex/p06-fixed-indexes-recovery` 从原checkpoint恢复，在clean原4d先task-start `8aa4fb734622473b95a96876bf956c81` / checkpoint `checkpoints/20261021T045629Z-before-p06-fixed-indexes-recovery-ec124412`，再FF到17d66c66。原基点仍4d。16非共享文件的bytes/modes/SHA与新21备份6b4f22da完全一致，5共享留latestmain交root串行合成，不能用旧policy覆盖900 watchdog。完整21义务移交与独立review后旧任务仅abandon，保留现场，不标完成。

PR10工具修复已完成精确main本地5gate/checkpoint及PR/main两版本CI验收；这不证明本片新checkout通过。此修订只有内部验收接线，无用户行为或产物格式变化。先记录再写共享源码：以17d为底合入原5共享P06增量，全部原commands/suite预算/planned/strict100%及原21排除保留。3driver实际新增900+300+300秒；当前全部10ready/29commands加原600秒安装上传为16320秒/272分钟，普通CI采用275分钟，release360不变。这是工程job上限，不调产品原5秒build/1秒query/512MiB/1MiB文件阈值。上游后来增加命令必须按当时实际policy重算，不沿用275。

root同步共享手册/追踪的局部证据与已闭合CF1-A边界；19unit、223Python/3808及三driver只绑定旧冻结077d94dd，不能转为本次结果。后续完整原4d plan/check、hook、postcommit/task-finish、当前PR双CI和精确main重验均待执行。本次没有P03/P04/PG/B-L真实配对、I1或生产性能baseline；原始raw最终head显式归档仍待完成。


## CI 硬上限负例夹具适配（源码前记录）

独立并行P03在同一17d基础追加3driver/275分钟组合后，首次完整harness真实失败：105项中硬上限负例将整个表达式写死release367/change250，先在change15000秒不足16320秒失败，尚未检验预期hosted360上限。P03原failed报告/日志保留；P06尚未运行，不把该并行失败冒充本片已运行。Root合成预算时漏核这个负例前提，现仅修现有夹具：从当前实际workflow表达式只把release数值替换为367，保留当前有效change分支，让assertRaisesRegex实际命中hosted job。原validator/360拒绝与future-ready测试、正式275/release360/各命令/产品预算均不变，不新增另一套测试或跳过负例。此为内部验收夹具、无用户行为变化；先冻结新24文件源并独立review，后续在新完整原4d检查验证，不盲跑已知旧夹具。

## 恢复树 INITIAL 全新证据与独立复核

2026-10-21 本轮在 `/Users/chad/dev/guradb-p06-fixed-indexes-recovered` / `codex/p06-fixed-indexes-recovery` 进行；active task `8aa4fb734622473b95a96876bf956c81`，原base仍 `4d6baca888421d90f146679ef71b0e555fe60881`，HEAD为 `17d66c66a067eebe73280ce8d3488fb4f7cdcfe9`。运行绑定24文件清单 `artifacts/fixed-indexes-recovery/ci-fixture-fix/review-manifest.json` SHA-256 `ca86467e9557eadbc08f597442518fb3db70c43720f0babf8a0c933ee9dda27d`；旧任务仅abandon、旧dirty/driver/失败现场保留，不缩小新原4d范围。

新树独立venv按三份锁安装且pip check通过。仅CoW复制已静止donor的ordinary `target/debug` 依赖缓存，再clean六个workspace crate；开始检查前LLVM/profile目录为空，没有复制旧覆盖结果。随后实际命令 `.venv/bin/python scripts/harness.py check --scope change --base 4d6baca888421d90f146679ef71b0e555fe60881` 首次执行，无自动重跑。报告为 `artifacts/harness/20261021T062755Z-98f8d0e9/report.json`，SHA-256 `d1c849e602e32eb5792010154fa043b7f9d05836e7234743eb99770d25ed5845`，harness checkout digest `a8a4a51dc88bdbc6e0814568dc0d39558499ded0df5876cd9396248f9b331581`。

实际9/9套门禁PASS：repository、contracts、harness-tests、policy、python、functional、performance-smoke、stability-component、unit-coverage；26条实际命令均passed/returncode0。Python全量225项测试、3808/3808适用执行行、missing0/excluded0。Rust在unit-coverage中实际编译/运行测试并采集，按lcov唯一源码行重算：raw3344、raw covered3323，保留原15组21行排除，eligible3323/3323、missing0；排除文件SHA `16b5ae011d146469cff7114b6f22fa0e5e89355ef7879ef00f148d8527458bb7` 与17d原件及逐行文本不变。没有把未选中的独立Rust suite/fmt/clippy称作已运行。

同次harness的三个真实driver使用全新目录，均源码前后不变，driver源码JSON摘要为 `883a2a3fd104db627ed4fea3dbbf865cab8fffa737d5cabe5c83b4068280591f`，与harness包含模式的checkout算法分开：

| mode / 同次run子目录 | report.json SHA-256 | 实际观察 |
| --- | --- | --- |
| functional / `fixed-indexes-functional` | `399b4004009dc8024c2838e1b5d2a480dffb8ede3b590c7d76a747bb001f4b1f` | 全11行、10vector+1显式NULL、3个物理row group；8组查询及重复读取，全ledger/定位/排序/分数真值一致 |
| performance / `fixed-indexes-performance` | `8885813437c054fb9ca436eab902801a82d69b1966fd3ffb4f25e3e146810c81` | 每artifact含输入pipeline 5.746334/5.568167ms，文件12649/12612bytes，builder进程RSS67289088bytes；原5秒/1秒/512MiB/1MiB预算均通过 |
| fault / `fixed-indexes-fault` | `67030a41539b13015e1078d2e71c15dcd2eac193ede59a1bb6a70c6e09caa580` | 13项故障按预期拒绝且对应case没有complete返回，保留失败staging；不是发布/ingest崩溃恢复证明 |

P01独立源码/物理schema/完整ledger/数学和小型raw审查位于 `/Users/chad/dev/guradb-p03-fixed-objects/artifacts/p06-initial-source-raw-review/review.json`，SHA-256 `3d7b0be0f6f784ebeace2ee8ab4bd119a2405d8f3650b0a2d6d963cd62187b3b`，PASS。独立核P01 manifest、真实Parquet footer的101–106物理字段/1–6resource映射和4/4/3行组、显式10vector+1NULL、每正常driver8组/重复候选与locator、binary64分数，最大误差0；该只读审查解码footer而未重新运行压缩cell解码，物理全行读取以已执行driver的独立PyArrow audit及其全11行报告为证。

plan_audit独立全源/门禁/全部raw/profile审查位于 `/Users/chad/dev/guradb-worker-poll-recovered/artifacts/p06-initial-review/review.json`，SHA-256 `5d9c8e05391efc665fe425f7c145c159b0d2ab13af03a815a80c0c0c1643da22`，PASS。实际核24源与wrapper/三个driver前后身份、26条精确argv/log SHA、2744份保留raw共195008252bytes、覆盖八原件及原排除集合。后续Cargo前保全的793份profraw/profdata共476521376bytes，原/保留两端字节、SHA和mode逐份一致；没有以缓存/旧profile冒充新采集。原件/保全索引为 `artifacts/fixed-indexes-recovery/initial-20261021T062755Z-1897c1e5/`，长期共同Git归档仍待最终head。

故障语义边界单列：每个case的 `complete_output_emitted=false` 只表示该失败调用未返回完整成功，不证明整个scope零费，也没有为每个新semantic-reader故障保存独立数值Usage。shared/limited scope实际output_bytes为0；guarded scope为2284，来自注入撤权/取消前的一次显式成功读取，后续失败不能回滚先前费用。scope在失败ObjectReadPort调用前保守预扣expected bytes，这不是短读/缺对象的实际wire传输计数；真实P03后端累计字节/重试和共享父scope账本接线仍pending。

本轮为本机Python3.14.7/PyArrow22、synthetic小工作集；新reader进程无应用内容缓存，OS缓存未清除，不认证冷存储、倒排seek/ANN/真实encoder/业务相关性或产品性能基线。source locator/processing仍trusted fixture，P03/P04/B-L/PG/P05/P10真实接线及I1未完成。此次只更新三份leaf结果文档，其余21源/共享接线不变；新文档冻结与最终head的hook/提交后原base检查、task-finish/最终raw归档、PR双CI/expected-head合入/精确main验收及main CI仍pending。旧FAIL与旧driver保留历史结论，不挪为新通过。

root在实际核读三leaf差异与两独审记录后接收whole本树，只同步用户导航和实施追踪的旧待测状态。本段与两导航只描述ca864 INITIAL证据，不改其它源/接线/receipt/预算或把最终head判通过；作者三doc冻结81122及原运行ca864分开保留。

## clean主线接续的内部状态（2026-10-21创建时）

PR11私有Compiler提取已完整闭合至1e4f6a6c26eb28982f4b61cc75aa05e290211809：PR39555312514和main39558459736双Python均SUCCESS，精确17d→merge本地9suite/24命令报告bc049da2/checkpoint071032通过，root实际834raw三端核验72e21975。此上游没有新增SQL能力或P05 CF1-A/I1语义。

本片从原4d checkpoint在新/Users/chad/dev/guradb-p06-fixed-indexes-main1、codex/p06-fixed-indexes-main1接续，clean4d先task-start7856fbed099242b6aadc70b3d9b9cc74/checkpoint checkpoints/20261021T072724Z-before-p06-fixed-indexes-main1-22994eb9，再cleanFF1e4。24bytes/mode逐项等37953备份54d2253b，原base仍完整4d；8旧同名baseline与16新路径逐项准入后恢复，index为空，5上游P05路径无交集且当前字节未改。恢复记录216b4902与真实操作/时序在本树artifacts/fixed-indexes-main1/source-recovery-20261021T072724Z/。root已实际核24backup/receipt/5上游，随后只补本内部状态和进度两文档，不改其它22源/门禁。

旧8aa恢复树与5d6原树dirty/raw、全部旧INITIAL/局部driver/profile保留其原HEAD/checkout含义；8aa只有完整承接确认后才abandon，不标完成。当前新树matchingvenv/完整原4d plan、正常hook首次全check、提交后原4d cleanHEAD freshpost、独立审查/task-finish/长期raw归档、PR及主线验收仍pending。真实P03/P04/B-L/PG/P05/P10与I1未配对；不能把ca864 INITIAL9suite/26命令挪为新1e4 checkout已测。若后续main多driver，root重算真实ready预算并合成共享接线，不复制whole policy、抬产品预算或缩原始范围。
