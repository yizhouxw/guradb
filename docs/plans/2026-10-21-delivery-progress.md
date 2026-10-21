# 概要设计实施追踪

开始日期：2026-10-21（Asia/Shanghai）。权威范围为[最新实施计划](2026-10-20-parallel-delivery.md)，决策见[ADR0020](../decisions/0020-product-review-and-vertical-delivery.md)。此表记录实施事实，不改变P00–P20、I1–I3、G1–G5和M0–M4的完成条件；子片完成不能标整个工作包完成。

## 起点与本轮验收

起始主线与`origin/main`均为`169563cf4f0d36e7be8ad6600c941e0139126cf7`；原工作区干净，原任务receipt已完成，没有搬动或暂存其他任务文件。已核对Git作者、hook、Docker和锁定依赖入口。历史M0/M1/M2报告不能代替本轮代码证据。

第一批可观察验收：贡献者可用共同读描述符进行Rust/Python编码互操作，缺版本/预算/未知必需能力明确拒绝；质量负责人可取得固定摘要、许可明确的图文设计样本及独立关系/检索/训练组真值。两者均不代表真实目录、对象后端或SQL/HTTP已经接通。CF1-A冻结并合入后才能开工对应生产子片。

支持白名单：受保护固定输入的共同读合同、独立synthetic设计fixture、已有alpha兼容。当前新增writer、自动GC、训练消费、多机部署、首云认证和生产发布均未验收；不能由本文件授权部署、配置远端保护或宣称数值SLO。没有客户样本时业务相关性/价值验证保持missing，不能由算法真值代替。

## owner、文件范围与交接

各任务以起始SHA独立建立`codex/`分支/worktree和task receipt；本表路径为本轮实际分配，后续任务开工前另登记。性能测量只允许一个任务独占；轻量合同测试可并行。审查者只读实现，不与作者共写同一worktree。

| 任务 / owner | 分支 / worktree | 独占文件域 / 禁止区 | 依赖与当前状态 |
| --- | --- | --- | --- |
| 进度与集成 / root | `codex/delivery-progress` / `/Users/chad/dev/guradb-delivery-progress`；后续`codex/w0-status-local-simulation` / `/Users/chad/dev/guradb-w0-status` | 本追踪、原实施计划状态；不编辑模块代码 | 启动PR#6已完整验收；进度更新从84c07af2开始，独立receipt；无运行时变化 |
| P00 CF1-A / p00_cf1a | `codex/p00-cf1a-contracts` / `/Users/chad/dev/guradb-p00-cf1a` | `modules/common/cf1a_*.py`、`crates/guradb-common/src/cf1a/`及`src/lib.rs`接线、crate的`tests/unit/cf1a*.rs`和`examples/cf1a_roundtrip.rs`；`api/cf1a/`；`tests/contracts/test_cf1a_contract.py`、`tests/contracts/cf1a_roundtrip.py`、`tests/unit/test_cf1a_*.py`；`docs/interfaces/cf1a-*`、`docs/design/cf1a-*`、`docs/user/development.md`与手册入口；禁止P01下列三个tests域、业务模块、harness和根计划 | 独立起点169563cf；独立源码复核已通过，最终门禁/PR待完成 |
| P01首片 / p01_oracles | `codex/p01-outline-oracles` / `/Users/chad/dev/guradb-p01-oracles` | `tests/fixtures/outline/`、`tests/outline_oracles/`、`tests/contracts/test_outline_oracles.py`、`docs/design/outline-oracles-change-plan.md`、`docs/user/outline-oracles.md`；禁止公共schema、生产排名/选择和现有阈值 | PR#7首片主线验收完成；CF1-A映射在冻结后复核，业务样本义务未完成 |

独立合同/计划复核先核查版本、授权、源与发布双fencing、局部校验与pin责任；实现复核另读diff、负例、复杂度和证据。根计划和后续组合根由root串行接线，其他owner需通过交接提出变更，不能跨包复制实现或语义。

## 逐包状态

| 包 | 当前状态 / 下一实物依赖 |
| --- | --- |
| P00 | CF1-A/1.0首片已冻结，经PR#9合入4d6baca并完成精确主线10项门禁、真实12golden/23拒绝码双向互通和两版本PR/主线CI；B/C仍待下游反馈与独立验收 |
| P01 | synthetic图文/组真值首片已合入84c07af2并完成本地/远端主线验收；业务样本/人工相关性、真实模型/框架及生产规模预算未完成 |
| P02 | 待CF1-A/P01，先共同目录绑定与真实PG |
| P03 | 固定ObjectRef本机读取恢复树已通过原4d完整INITIAL九项门禁（232项Python/3804行零排除、Rust3323行与原21行豁免、真实三driver），报告0e436457及作者外复核；结果文档更新后的正常hook/提交后原范围检查、PR与精确main验证待完成，PG/P04/I1未接通 |
| P04 | 待P03/CF1-A/P01，先固定源ReadBatch；生命周期部分依赖B |
| P05 | 待CF1-A/P01，先共同请求/关系/精确计划；训练选择依赖C |
| P06 | 待CF1-A/P01，先固定revision产物与覆盖证明 |
| P07 | 待P02交权及CF1-B，持久Job/Pin/源回执/GC |
| P08 | 待CF1-A/P02/P05，正式登记/查询入口；媒体/导入依赖B |
| P09 | 待CF1-C/P04/P05/P07，真实框架多worker/尾批消费 |
| P10 | 待P03–P06，按需provider/真实算子/媒体批回表 |
| P11 | 待CF1-B/P03/P04/P06/P07/P08，源提交与刷新编排 |
| P12 | 待CF1-A/P03，最小安装/观测可提前；正式接线在P13 |
| P13 | 待共同读子片，按I1→I2→I3串行接线；G1未开始验收 |
| P14 | 待接口冻结可做driver，正式质量/成本测量须P13候选 |
| P15 | 待P14及获准三台独立环境；G3前必须P17a真实接线 |
| P16 | 待P15/P14/P17a，完整M3集成 |
| P17a | 待CF1-A及P03/P08身份/凭据合同，远程身份/传输 |
| P17b | 待选定首云/P15/P17a/P03/P08及测试账户/预算；尚无云认证证据 |
| P18 | 待P07/P11/P12/P15接口及PG主备/WAL/隔离恢复环境 |
| P19 | 待真实候选与环境，完整性能/故障/长稳；不得用组件门禁代替 |
| P20 | 待P16/P17a/P17b/P18/P19，全部G5/M4义务及独立复核后才可发布 |

2026-10-21用户指定“使用本机模拟云环境”。后续使用本机隔离容器/网络/数据目录准备对象存储、多节点和PG HA/PITR演练，不创建外部付费资源。报告记录固定镜像、共享物理故障域、端口/命名空间、注入与清理责任；本机模拟不等于真实云、三台独立物理主机或生产认证。原真实环境义务保留missing，继续不依赖该环境的实现和模拟验收。

对象后端预探测使用既有固定SeaweedFS 3.97镜像、同一测试bucket：两次写取得不同VersionId，覆盖后旧版本整对象与Range读取的字节、206、Content-Range及返回版本匹配。仅为P03前置后端探测，不证明P03权限/完整性/累计预算/缓存/故障通过。早先第二bucket超时的日志定位为`volume.max=1`不能分配第二collection；未据此误判为不支持版本控制，也未修改基线配置消除产品回归。产物在原工作区`/Users/chad/dev/guradb/artifacts/local-cloud-single-collection-20261021/backend-capabilities.json`；失败日志为`artifacts/local-cloud-probe-20261021/gura-4b8dd55626d6-0.log`及`artifacts/local-cloud-probe-direct-20261021/`，复现脚本为`artifacts/local_cloud_pinned_probe.py`。这些是本地前置记录，P03正式driver须重新创建隔离环境并归档本片证据，不能复用为模块验收。

P00首次完整检查记录在其worktree的`artifacts/harness/20261021T001010Z-2bffa650/`。历史Rust Clippy的`int_plus_one`与`large_enum_variant`诊断已修复，失败现场保留；该失败报告没有用于通过结论。修后独立复核、重新编译、互通、覆盖率与完整门禁以及PR/主线交付均已另行完成，精确证据如下。

P03任务为`653a8ca54b7845ccb03ecf777afbaf36`，分支`codex/p03-fixed-objects`，目录`/Users/chad/dev/guradb-p03-fixed-objects`，原始base为4d6baca，checkpoint为`checkpoints/20261021T015433Z-before-p03-fixed-objects-dd387582`。p01_oracles独占storage fixed_*、对应unit/support与driver/三份先行文档；root在明确交权后串行接用户导航、此追踪与harness/architecture/policy及防漏选测试。R1修订的19文件清单SHA为`aa42b5f1b7a34adb560764ca889338179c9de53899109d65828ca04dc8738d3b`；root已实际读源码与新负例并重算全部摘要。旧18项单元只绑定历史SHA。后续telemetry候选25文件清单7fd121054724d2697997b9b88958e6204a9ed616bdf14254d5d441063237b97c已重新验收26项单元、230项Python测试/3804行零排除及三种真实本机driver，精确报告SHA/路径见[变更计划](../design/fixed-objects-change-plan.md)，root已独立读原始记录并核验。以上为旧树历史局部证据；恢复树后续已重新完成原4d范围INITIAL九项门禁，精确结果见本页末段，不能把旧checkout或本轮更新后的文档SHA当新检查通过。

## 已验收的W0首片

CF1-A [PR#9](https://github.com/yizhouxw/guradb/pull/9) head为`e0abf74728e8797133268a3ab020c4369dc36f6e`，合并前main为`8198658bc768a96638ad70a12948f3775a5cbab2`，merge为`4d6baca888421d90f146679ef71b0e555fe60881`。精确主线报告`artifacts/harness/20261021T013721Z-42424eaa/report.json`的10项/26命令全通过，报告SHA为`1ac66d36a01bb586e309d38ae31d5718e164cc5d863f1a6e7d8553213b4a0225`，checkout为`1695dea8b5192f908521aa42ebffa14d6113acbefa1bc0f45f4ca4a74bc4ef35`；checkpoint为`checkpoints/20261021T015015Z-p00-cf1a-main-verified-5ce1adab`。真实跨语言互通重新编译运行，raw archive位于共同Git的`guradb/roundtrip/5ef9a7e666765046be75ee59f7f553d7abbc4f99f0ac7cd5a08736987f5a421e`；[PR CI](https://github.com/yizhouxw/guradb/actions/runs/39525801267)和[精确主线push CI](https://github.com/yizhouxw/guradb/actions/runs/39528308712)的Python3.11/3.14均success。此片仅为离线合同，不证明PG/对象/源/索引已真实接线。

| 交付 | 精确代码、检查与恢复证据 | 已验证边界 / 未完成项 |
| --- | --- | --- |
| 进度入口[PR#6](https://github.com/yizhouxw/guradb/pull/6) | head `196471920b4d62b05c423a4cddf7bad4d76a2cfb`；merge `ad68168a3f397ce42cb13415204f23b1962024dd`；分支receipt `22a4a985d3cf4ce887a058f37c23d1f7`；主线报告 `artifacts/harness/20261020T233518Z-cbc9e706/report.json`，checkpoint `checkpoints/20261020T233616Z-delivery-progress-main-verified-8b365ecf` | plan_audit独立复核、文档四项门禁及两版本PR/主线CI通过；仅计划状态，不新增运行时 |
| synthetic样板与独立真值[PR#7](https://github.com/yizhouxw/guradb/pull/7) | 原始base `169563cf4f0d36e7be8ad6600c941e0139126cf7`；head `3bddb5517084d59efceb50da2544dd9fd6279d26`；合并前main `ad68168a3f397ce42cb13415204f23b1962024dd`；merge `84c07af2aa8cdb74e23dbdb3b3d63faa52fcae0d`；分支receipt `b9ddc551db914a43b10172ddd5780205`、最终报告 `artifacts/harness/20261020T234754Z-53285edb/report.json`及checkpoint `checkpoints/20261020T235107Z-p01-outline-oracles-done-6fcef9e3` | 16项独立契约测试；12版本/11可见/3样本，固定许可/摘要，关系、精确L2/BM25/图与训练组/成员真值，int8/NULL/版本/重复/缺模态负例。root独立复核，无阻断；不证明实际模型或产品质量 |

P01主线在独立detached worktree `/Users/chad/dev/guradb-pr7-integration` 对完整合入范围运行change check，contracts/harness-tests/policy/repository/unit-coverage均通过；报告 `artifacts/harness/20261021T000314Z-ca37e544/report.json`，checkout `28cddb9511ff593aef79b2488e8bb964911223f3a62f4faf995289e363daf9ca`，checkpoint `checkpoints/20261021T000824Z-p01-oracles-main-verified-83215387`，归档 `guradb/evidence/f10c362503dc5b5626c3e8f93928529b729127f5cfcd413749eb102059393c34`（共同Git目录）。[PR run](https://github.com/yizhouxw/guradb/actions/runs/39517823933)与[精确主线push run](https://github.com/yizhouxw/guradb/actions/runs/39518869022)的Python3.11/3.14两个job均success。

P01[离线使用合同](../user/outline-oracles.md)与fixture manifest `455fc7a3e8c75a1c5446ecc52a3ead105f930607957f8f10eaaca8ffb1d32f94`提供可复现入口。新包仍须重测当前候选，不复用此表旧证据；原G1–G5均未通过，整体实施任务继续进行。

## 每片交付与恢复

每片记录原始base、head、PR、check报告、独立复核、receipt/checkpoint；每次同步保留原始范围重验。通过当前PR测试合并树的Python3.11/3.14两个quality job后，以expected head SHA、merge commit串行合入；在独立干净worktree对合并前main至merge SHA运行check并核对主线CI，前一集成未验收不继续下一PR。

此追踪首次提交只有文档状态变化，采用默认change门禁，不新增数据库功能或性能声明。数据库切片必须执行其实际plan选出的语言/功能/性能/故障/覆盖率门禁。两次无新证据失败后定位根因并保存现场；错误恢复按[恢复流程](../../harness/version-control.md)，不破坏性覆盖已有目录。代码回退不撤销数据或外部副作用，持久包另留对账与补偿证据。

首次启动的代码绑定报告、复核和checkpoint在`delivery-progress`任务receipt归档；当前进度更新由`w0-status-local-simulation`独立receipt记录，门禁和最终提交证据待完成。本文件中的实施中状态不能当作任何门槛通过证据。


P03原始范围恢复：旧dirty树与task653a及全部局部raw保留；新 `/Users/chad/dev/guradb-p03-fixed-objects-recovered`、branch `codex/p03-fixed-objects-recovery`、task `aa7ad841fd3a456ea99eb2e1ddcfd8ca` 在clean原4d先启动，再FF合入PR10的17d。19独占源码逐字转移，root串行合成6共享域，保留900秒coverage工程watchdog。增加3条driver后普通CI按实际ready命令重算为275分钟，并明确排除Lab两份私有测试配置；各产品/组件预算、原负例及覆盖豁免不变。恢复当时，完整原4d范围的新checkout验收与实际上传边界均待运行；现本地INITIAL见下，实际上传边界仍待验证。旧26/230/3804与三driver结果不能代替新fullcheck。恢复当时PR10双版本PR CI已成功、精确main验证仍进行中；现root已核验merge17d的main报告044402-982e5f80（SHA6d0e4932cf0c34fc263caf526ad00c013ad640ca4ae28adccaeea3d91ffe45ec）、checkpoint044927-pr10-main-verified-935740fd及PR39544118302/main push39545360623两Python版本均SUCCESS，已闭合。P03首次新INITIAL原472440范围运行9suites/33paths，报告b76b292d保留FAIL：八suite分别通过，仅既有hosted-limit负例的change250夹具前提未适配新272最低预算而失败。按先行计划仅修该夹具并冻结28文件后重新执行完整INITIAL；首FAIL原样保留，不拼其它局部结果为通过。

本轮新28文件manifest64f1cd3a在独占窗口先跑完整CIworkflow模块5tests，再以matching新venv运行原4d完整INITIAL九套件/33paths/26命令，全PASS；报告 `artifacts/harness/20261021T053114Z-e7619721/report.json` SHA `0e4364576a90dc69331eca368367e25f42eed3590d3ba251572338c5f28f965b`、checkout `e8798305c8b4fd87d31296e8c42fe3b94386c1432c3ae2ec52a4e3c04af59998`。Python232项/3804行零排除、Rust3323/3323和原21行豁免、9phase起止与3真实driver均重测。root匹配解释器validate_report、完整argv/log/hash/输入身份及28scope累计计量和期限/关闭记录已独立核验，review8ccce124；新790 profiles在任何后续cargo前保全，旧首FAIL/793profiles保留。本轮随后只更新结果文档和导航，新的docSHA仍需最终commit精确原范围postcheck。正常hook/commit/task-finish/公开raw归档、当前PR双Python CI/实际上传ZIP私有配置排除、merge后精确main本地及双CI仍待完成；PG/P04/I1、真实云、多机与完整产品门禁仍missing。

P03当前source-only接续树为/Users/chad/dev/guradb-p03-fixed-objects-main1（codex/p03-fixed-objects-main1/task55eb29fb62c645c48dc205760a089a2c），clean原4d先receipt再cleanFF1e4，完整28源码/模式等7ba8备份、5上游P05文件未变，root已复核；仅内部状态文字更新。旧aa7现场/receipt仍待确认全部承接后abandon，保留首次FAIL及原9suite INITIAL。新checkout正常hook/原base提交后检查、PR/ZIP排除认证及I1仍pending；PR11精确main本地已过，双mainCI尚运行，禁止下一PR提前合入。
