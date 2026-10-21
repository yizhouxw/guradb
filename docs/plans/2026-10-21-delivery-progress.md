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
| P00 | CF1-A稳定稿独立源码审查、12组真实跨语言golden/23组拒绝错误码比对、新增Python/Rust执行行覆盖已有局部证据；首次整仓check发现两条Clippy错误，修复后须完整重验，尚未freeze；B/C待A复核与下游反馈 |
| P01 | synthetic图文/组真值首片已合入84c07af2并完成本地/远端主线验收；业务样本/人工相关性、真实模型/框架及生产规模预算未完成 |
| P02 | 待CF1-A/P01，先共同目录绑定与真实PG |
| P03 | 待CF1-A固定ObjectRef，先认证对象后端的range/version/checksum |
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

P00首次完整检查记录在其worktree的`artifacts/harness/20261021T001010Z-2bffa650/`。已发现Rust Clippy的`int_plus_one`与`large_enum_variant`诊断；失败现场保留，不能将同次其他suite通过拼成修复后报告。修复需独立复核并重新编译、跨语言互通、覆盖率及完整门禁，提交与主线交付仍待完成。

## 已验收的W0首片

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
