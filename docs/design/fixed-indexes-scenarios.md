# P06 固定物理索引场景映射

状态：恢复树24文件冻结下首次完整INITIAL9套/26命令、Python3808行、Rust3323适用行与原21排除、三个全新真实driver均PASS；源码/算法/定位与全部raw/profile两轮独立复核PASS。最终head/hook/提交/PR/main及真实I1仍pending，本次仅更新结果文档。手册：[fixed indexes](../user/fixed-indexes.md)；计划：[变更计划](fixed-indexes-change-plan.md)。原base仍4d6baca，原先行patch及旧19单元/Python223/三driver历史证据保留；最新运行清单及报告在文末，不把文档更新当新checkout已测。

| 场景 | 正常/拒绝断言 | 当前本机证据及未覆盖边界 |
| --- | --- | --- |
| FIX-N01 真实物理产物 | 双format真实写盘/fsync，销毁builder后子进程经ObjectReadPort重开；不读预置候选 | functional与物理unit通过；独立审查实际文件/重开输出 |
| FIX-N02 全coverage真值 | P01 view-v2全部11行、10vector+1显式null mask；BM25 N11/total22/df3；完整ledger和所有tf/vector/locator对照，不只top-k | 两正常driver均11行完整ledger、3 row group、独立Parquet/P01对照通过 |
| FIX-N03 A候选 | 全envelope context/query SHA、模型/config/processing、正平方距/降序BM25、精确tie、route窗口及ids交集 | 每正常driver8组查询/重复读取，误差0；无match/unknownids另有unit |
| FIX-E01 身份/NULL/源重写 | 重复/缺ID、非NULL feature缺失/假NULL、错父/模型/源/坐标拒绝；源重写新revision，显式version与派生version分开 | unit与旧固定ref读取重写源的fault拒绝通过；真实源新revision登记仍待P02/P04 |
| FIX-E02 严格格式与完整性 | unknown/duplicate/missing字段、坏hash/header/stats/vector/config/coverage/mapping、错format/维数/finite边界拒绝 | unit与真实文件改写/短读/缺对象fault通过 |
| FIX-E03 预算/权限/取消 | 当前授权每请求/输出重检，撤权/到期/取消/超限不输出complete成功；usage累计不重置 | 新fault13项均无complete返回；guarded scope先前成功读取已花2284输出bytes，不误报scope零费；失败对象预扣不是实际wire，不证明真实授权/后端计量服务 |
| FIX-E04 封存恢复 | existing目标conflict，fsync/写失败无descriptor/发布，保留现场；旧artifact不覆盖 | unit/fault验证冲突、fsync失败与staging保留；新目录恢复操作未执行 |
| FIX-P01 有界成本 | 固定输入/质量、每build≤5s、query≤1s、RSS≤512MiB、文件≤1MiB；披露OS cache与synthetic范围 | performance原预算通过；新子进程/已有OS缓存，非产品或冷环境baseline |
| FIX-LIMIT 接线限制 | locator/processing是trusted fixture，P04/B-L/真实P03/PG/P05/P10未认证不得称I1；无ANN/Graph/实际encoder/业务baseline | 独立review明确module-only；所有真实配对与I1继续pending |
| FIX-R01 单调期限 | 冻结/回拨wall时推进mono仍到期；auth或最终cancel回调消耗时间后取fresh wall/mono拒绝，包括cancel返回False仍已过期 | 19项unit中的确定性clock/authority/cancel负例通过 |
| FIX-R02 物理schema | 真实Parquet field IDs/type/nullability逐项核对，source SHA不复用resource角色域 | 独立audit/root核对实际101–106→1–6双域与Parquet footer通过 |
| FIX-R03 证据生命周期 | 新output、全source/commit/locks/env/input/artifact绑定，失败finally留证、源码变动不能绿 | 三driver实际前后源码一致；失败/源码变化/目录复用的unit负例通过，不冒充崩溃恢复 |

权限/预算：仅可信开发者本机构建与注入authority；无源写/目录发布/GC权限。A原有完整预算/deadline/ttl不省略。兼容：新私有version未知即拒绝，旧alpha行为不变，无数据迁移/公开服务/在途job与pin变化。

旧树实际驱动证据目录为 `artifacts/fixed-indexes/drivers-first-20261021T043251Z/`；functional/performance/fault的report SHA依次为 `10f14ffc3f974adb153cae2415868d0dea73cebee899769647b92303feab1ebe`、`658feba8889cff4a16e7f35b579e37cc73ef34cc485ac9f8612b045752ad668e`、`e0706580d52b2a872aa440318db9ffcab434f902f100df4a182ecb5aa6f4d4b5`。三项绑定旧冻结 `077d94dd449a46f188439b86ba13be6a941815fea09e0d1419115687f4549a3c`，driver源码JSON摘要为 `373846875a6b1f9f636295b0eb10761eac87f4a5419eb1707e8493892fcad9cf`（与harness模式感知checkout算法不同）。root独立复核 `artifacts/reviews/p06-driver-evidence/review.json` SHA `02575b747fcf00f7d4c6c023be70ed72bc238676f0cccd4b00a3b8dbd2dc8c12`。这些旧原件保留历史结论，不代替下面的恢复树fresh INITIAL；共同Git长期raw归档仍待最终head，task-finish不会自动复制全部外部raw。

## 恢复树 INITIAL 实测映射

本轮在active task `8aa4fb734622473b95a96876bf956c81`、原base `4d6baca888421d90f146679ef71b0e555fe60881`、HEAD `17d66c66a067eebe73280ce8d3488fb4f7cdcfe9` 下首次执行。源24清单SHA `ca86467e9557eadbc08f597442518fb3db70c43720f0babf8a0c933ee9dda27d`，检查/wrapper/三个driver前后身份一致；9/9套门禁、26条实际命令均PASS。总报告在恢复树 `artifacts/harness/20261021T062755Z-98f8d0e9/report.json`，SHA `d1c849e602e32eb5792010154fa043b7f9d05836e7234743eb99770d25ed5845`，checkout `a8a4a51dc88bdbc6e0814568dc0d39558499ded0df5876cd9396248f9b331581`。

| 验证义务 | 本轮实际结果及边界 |
| --- | --- |
| 严格覆盖 | 全量Python225项，3808/3808适用行，missing0/excluded0；Rust unit-coverage实际测试采集，lcov raw3344/covered3323，原15组21排除不变，eligible3323/3323、missing0；未另选独立Rust suite |
| FIX-N01/N02/R02 | functional/performance实际封存/fsync后新进程重开；全部11行/10向量+1显式NULL完整ledger，真实Parquet field101–106→resource1–6，4/4/3物理行组及逐ID/version/locator独立回查通过 |
| FIX-N03/P01 | 每正常driver8组查询及重复读取，BM25与squared_l2独立真值/顺序/分数/上下文均匹配，误差0；原5秒build/1秒query/512MiB/1MiB预算通过，OS缓存未清除 |
| FIX-E01/E02/E04 | 源重写旧固定ref、缺processing、短读/缺版本、坏stats/locator/header/ledger、已有目录及fsync等真实文件故障按预期拒绝；保留失败staging，不证明source发布/ingest生命周期 |
| FIX-E03/R01 | 13个fault case未返回complete；guarded scope在注入前已有成功输出2284bytes，不能称scope零费。逐新semantic-reader fault未保存每case数值Usage；对象失败前保守预扣expected bytes不是实际wire；真实P03累计计量/重试及父scope配对pending |
| FIX-R03 | 三个新输出目录，完整source/commit/locks/env/物理输入和产物摘要绑定；26命令日志与全部raw/profile由作者外独审，不复用旧077结果或覆盖原件 |

三份fresh `report.json` 分别位于同次run的 `fixed-indexes-functional`、`fixed-indexes-performance`、`fixed-indexes-fault`，SHA依次为 `399b4004009dc8024c2838e1b5d2a480dffb8ede3b590c7d76a747bb001f4b1f`、`8885813437c054fb9ca436eab902801a82d69b1966fd3ffb4f25e3e146810c81`、`67030a41539b13015e1078d2e71c15dcd2eac193ede59a1bb6a70c6e09caa580`。driver源码JSON摘要为 `883a2a3fd104db627ed4fea3dbbf865cab8fffa737d5cabe5c83b4068280591f`，不与harness模式感知checkout混用。

两轮作者外独审均PASS：P01的 `/Users/chad/dev/guradb-p03-fixed-objects/artifacts/p06-initial-source-raw-review/review.json` SHA `3d7b0be0f6f784ebeace2ee8ab4bd119a2405d8f3650b0a2d6d963cd62187b3b`，独立源码、footer/全ledger、数学/定位和小型raw核对；plan_audit的 `/Users/chad/dev/guradb-worker-poll-recovered/artifacts/p06-initial-review/review.json` SHA `5d9c8e05391efc665fe425f7c145c159b0d2ab13af03a815a80c0c0c1643da22`，全24源/26命令、2744raw和793份profile原/保全两端逐字节/SHA/mode核对，原21行排除保持。P01审查只独立解码footer，未重跑压缩cell解码；真实全行解码/比对由已执行driver的独立PyArrow audit证明。

此次只更新三leaf结果文档，不改其余21源/共享文件。新文档冻结及最终head/hook/提交后原base检查、task-finish/长期raw归档、PR双CI与精确main验收仍pending。trusted locator/processing fixture不等于P03/P04/B-L/PG/P05/P10真实配对，I1/真实模型/ANN/冷环境及产品性能仍未认证；旧FAIL与旧driver原件保留，不改判或挪用。
