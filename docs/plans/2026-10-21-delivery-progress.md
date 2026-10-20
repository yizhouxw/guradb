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
| 进度与集成 / root | `codex/delivery-progress` / `/Users/chad/dev/guradb-delivery-progress` | 本追踪、原实施计划状态；不编辑模块代码 | 固定起点169563cf；记录启动，无运行时变化 |
| P00 CF1-A / p00_cf1a | `codex/p00-cf1a-contracts` / `/Users/chad/dev/guradb-p00-cf1a` | `modules/common/cf1a_*.py`、`crates/guradb-common/src/cf1a/`及`src/lib.rs`接线、crate的`tests/unit/cf1a*.rs`和`examples/cf1a_roundtrip.rs`；`api/cf1a/`或`api/cf1a.schema.json`、`api/cf1a.golden.json`；`tests/contracts/test_cf1a_contract.py`、`tests/unit/test_cf1a_*.py`；`docs/interfaces/cf1a-*`、`docs/design/cf1a-*`、`docs/user/development.md`与手册入口；禁止P01下列三个tests域、业务模块、harness和根计划 | 独立起点169563cf；实施中，待复核/门禁/PR |
| P01首片 / p01_oracles | `codex/p01-outline-oracles` / `/Users/chad/dev/guradb-p01-oracles` | `tests/fixtures/outline/`、`tests/outline_oracles/`、`tests/contracts/test_outline_oracles.py`、`docs/design/outline-oracles-change-plan.md`、`docs/user/outline-oracles.md`；禁止公共schema、生产排名/选择和现有阈值 | 独立起点169563cf；实施中，CF1-A映射在冻结后复核 |

独立合同/计划复核先核查版本、授权、源与发布双fencing、局部校验与pin责任；实现复核另读diff、负例、复杂度和证据。根计划和后续组合根由root串行接线，其他owner需通过交接提出变更，不能跨包复制实现或语义。

## 逐包状态

| 包 | 当前状态 / 下一实物依赖 |
| --- | --- |
| P00 | CF1-A实施中；B/C待A复核与下游反馈，尚未freeze |
| P01 | synthetic图文/组真值首片实施中；业务样本/人工相关性未取得 |
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

当前只有本机Docker可用性已核对；没有把本机三进程记作三台主机。后续可先准备fixture/driver，但获准三机、云账户/预算、PG HA/PITR和持久证据存储需各自登记与实测。缺少外部环境时保持对应项missing，继续不依赖该环境的包。

## 每片交付与恢复

每片记录原始base、head、PR、check报告、独立复核、receipt/checkpoint；每次同步保留原始范围重验。通过当前PR测试合并树的Python3.11/3.14两个quality job后，以expected head SHA、merge commit串行合入；在独立干净worktree对合并前main至merge SHA运行check并核对主线CI，前一集成未验收不继续下一PR。

此追踪首次提交只有文档状态变化，采用默认change门禁，不新增数据库功能或性能声明。数据库切片必须执行其实际plan选出的语言/功能/性能/故障/覆盖率门禁。两次无新证据失败后定位根因并保存现场；错误恢复按[恢复流程](../../harness/version-control.md)，不破坏性覆盖已有目录。代码回退不撤销数据或外部副作用，持久包另留对账与补偿证据。

本轮最终代码绑定报告、复核和checkpoint在`delivery-progress`任务receipt归档；本文件中的实施中状态不能当作任何门槛通过证据。
