# 当前本机质量保障与 CI/CD 暂停

2026-10-24用户明确要求：暂时停用GitHub Actions CI/CD及PR CI卡点，当前使用本机自测保障代码合入质量；项目达到一定完整度后重新讨论。依据[ADR0023](../docs/decisions/0023-team-issues-and-local-quality.md)，优先于ADR0009/0019及旧计划的远端必需检查条款。

本地基础与后续工程任务按[CI基础执行台账](../docs/plans/2026-10-24-ci-foundation.md)推进（Refs [#43](https://github.com/yizhouxw/guradb/issues/43)）。该台账是合同与排程输入，不表示隔离、消费者接线、新模块资格或远端CI已经落实。本片无数据库用户行为、生产代码或质量政策变化。

## 当前执行状态

| 项目 | 当前规则 |
| --- | --- |
| GitHub质量工作流 | `Quality harness`，ID 387490345；先前停用快照为 `disabled_manually`，本片未复核实时API |
| GitHub诊断工作流 | `Frozen worker diagnosis`，ID 390094932；先前停用快照为 `disabled_manually`，本片未复核实时API |
| PR远端CI准入 | 暂停，不等待 `quality (Python 3.11)` / `quality (Python 3.14)` 或main push绿灯 |
| 本机质量 | 适用模块自测、真实配对/系统检查、独审、正常hook和精确main证据仍必需 |
| CD/发布 | 没有由本次决定授权部署；完整release、安全/恢复/环境义务保留 |

机器可读决定见[ci-state.json](ci-state.json)。当前质量工作流[YAML](../.github/workflows/check.yml)保留供未来恢复；诊断工作流的历史登记路径为`.github/workflows/worker-reproducer.yml`，当前树无该文件，其远端登记在先前快照中同样为停用。配置文件存在/仍有事件声明不表示远端工作流已启用。实际状态以GitHub API为准，新增或重命名workflow也须保持停用。2026-10-24执行停用后已核两工作流状态、无活动run；这是当时快照，后续管理员变更必须重新核对。

本片继续使用现有本地环境，不采购或注册runner。远端实时workflow开关、活动run、runner注册、套餐/配额和有效保护规则均为本片未核的未知项；不能从本文件或暂停政策推断这些API事实。

## 本地分层入口与资格

先安装[现有锁定依赖](README.md)，在独占任务树以原始基点 `B` 运行 `python scripts/harness.py plan --base B --level auto`；读取 `validation.profile` 的实际层级、命令和闭包，再运行相同范围的 `check`。顶层legacy impact摘要不代替实际profile。以下是现有入口及义务，示例中的 `B/M/ID` 须替换为实际SHA/批次，不是本片运行结果。

| 层级 | 实际入口与退出条件 |
| --- | --- |
| 文档/工程 | auto按实际路径选择documentation/engineering；本片文档应选择repository、policy、contracts、harness-tests。工程profile另有真实query-native回归；二者均不能宣称数据库M/P/S通过 |
| M 模块 | `check --base B --level module --module query` 等已登记profile；验证完整owner生产源、实际语言和自身真实依赖，及功能/拒绝/原性能/故障，不只测changed lines |
| P 真实配对 | `check --base B --level pair --module storage --module query` 仅适用于当前已登记旧配对；需要真实producer/consumer、独立oracle和同view/ID/version、权限、预算、取消、unknown及恢复证据 |
| S 系统 | 稳定批次由集成者在唯一窗口对精确main执行 `check --base M --level system --batch ID`，覆盖完整M→G及新route必要driver；旧系统driver不能认证新原生链 |
| R 发布 | `check --base all --level release`；完整performance/stability/soak目前planned，缺失仍FAIL，不能以M/P或文档通过替代 |

当前[registry](validation.toml)只给query/storage的`.rs`改动配置ready module，两者唯一component为legacy-m0，唯一pair为storage-query；ready只表示可执行映射，不表示本次已验收通过。它不等于新CF1-A共同视图链路。Python改动及common/catalog/connectors/index/cluster/gateway/client-api/cli/mcp没有对应独立ready映射，按实际范围扩大system或拒绝较窄请求；既有PG/P03/P04/P06 driver不自动授予新profile资格。

模块验证保持完整owner与未导入源；现行覆盖合同是Python全部自研生产源至少80%、Rust经原清单排除后的适用行100%，用合法整数交叉乘、total>0判定。Python不允许行排除，Rust原21行清单不扩。旧100%报告保留历史含义。当前scoped coverage仍要求owner同时有Python/Rust；未来仅实际无该语言时才能经盘点明确N/A，不能0/0成功，该适配尚待CI-4A实施/独审。

本次已授权取消PR的远端CI准入，不修改无关审批/分支保护。若平台仍有实际required status check阻断，集成者先读有效规则，再仅解除已授权的CI context并记录前后状态；不能据此关闭独立审查、允许强推或扩大部署权限。没有平台规则证据时不能声称保护已配置或已解除。

## 本机合入质量闭环

1. 模块负责人按[开发流程](development-workflow.md)对实际变更自测：单元/静态、真实依赖功能与负例，以及适用的性能/预算/故障。用现有harness/script，不把mock通过升级为系统通过。
2. 专职系统测试独立负责真实跨模块配对和用户旅程，独立oracle、同view/版本/权限、总预算/取消/unknown/清理/恢复；性能与长稳在受控环境单独验收。
3. 集成者核源码、依赖、文件范围、复核和本地报告，正常hook提交；合入后核精确main、适用检查、报告/checkpoint和远端SHA。只因实际修改、失败或未解决风险补验证，不为管理格式无风险重跑全部历史。
4. 当前CI记为 `PAUSED_BY_USER / NOT_RUN`；既有失败保留，不能改成PASS。缺少本地命令/证据、timeout/failure/missing仍不能标绿。模块、配对、main和release分层记录，完整performance/stability/soak planned仍阻断release。

本机模块/组件预算、输入、原适用超时、完整源分母和原覆盖排除不变；覆盖阈值按上节现行Python80%/Rust100%合同。托管GitHub runner时间容量检查作为恢复CI前义务保留，不成为本机质量阶段新建分片/union工具的前置。

每项任务保存原始B、当前H、审阅H及真实命令/报告/receipt/checkpoint；H更新后重新核完整范围与独审。集成前保存M，以expected H串行merge commit，再在独立干净目录对实际G验证完整M→G、建checkpoint并确认远端SHA。PR合成checkout SHA与H/实际G分别记录，预览merge SHA不是已合入G。原始B不被CI当前PR base替代。

现有harness校验范围、源/profile/命令/日志哈希及前后身份，并归档可验证报告；它不证明审查者独立、真实driver语义或跨宿主资源锁。PM人工分配唯一文件写权及重测/coverage/性能/迁移/main窗口，作者与非作者分离。现有coverage锁仅覆盖同checkout，共享CPU/Docker tag/registry仍需排窗；独立target、缓存、消费者扩散和远端身份接线的工程缺口见台账，不能称已实现。

失败保留日志、diff、原始测量/raw与现场；同条件两次无新证据失败停止盲试。网络/S3独立阻塞先给20分钟排障时间盒，交PM记录owner/下一动作；该时间盒不改变driver原timeout或负载。恢复在新目录按[Git恢复流程](version-control.md)进行，必要修复/revert另走PR，不覆盖原失败。报告/命令日志归档不等于全部raw已异地备份。

## 恢复CI/CD的条件

以下四项分别决定，任何一项的文档交付都不自动批准其它项：

| 项目 | 本阶段决定与后续准入 |
| --- | --- |
| 现有本地执行基础 | 继续使用现有环境，按实际本地分层检查；CI-1只整理合同/台账，无新隔离或自动调度能力 |
| 后续独立worker环境 | 机器/预算/运维owner、网络/S3通路、隔离、容量、取消及证据保留待确定；未采购/注册，不作为无关接口文档的前置 |
| Quality Actions恢复与触发 | 保持暂停；明确环境、真实容量及有限候选成功/失败/取消/缺证据验证后，由用户另行授权具体PR/main/manual/schedule触发；历史diagnosis不随之自动开启 |
| PR required contexts/有效保护 | 与恢复Actions分开；管理员读实际规则、确认稳定且唯一context和真实候选结果后再获授权设置，不撤独审、不扩大bypass |

由用户重新讨论并明确授权后，先固定可发布范围、受控runner/环境、真实全部命令及容量、凭据/权限、日志与报告保留、必要的分段证据语义；再实际运行候选、核对应head/base和结果，才重新讨论PR required checks与平台强制。

恢复操作应更新ADR与机器决定、核远端workflow状态及有效保护规则；不能仅修改YAML或恢复开关便声称CI通过。CI/CD优化独立Issue管理，不自动混入数据库交付。历史Actions artifacts通常仅保留14天，必要证据继续在本地按原规则归档；本地归档不等于异地备份。

CD仍需明确不可变构建物、版本/摘要、部署目标、身份与授权、健康检查、迁移/备份、unknown对账及恢复/补偿。关闭CI或代码回退不撤销外部副作用，也不自动开启部署。

## 保留的PR15/16实现与预算（当前不启用远端）

保留auto/module/pair/system/release选择、完整生产分母、选择器/配置指纹、真实argv/timeout、前后源码与证据绑定。workflow保留main-only push、无过滤PR、手动及定时release、双Python矩阵、固定Actions SHA和既有私配排除；配置不表示启用或运行，未来上传范围/脱敏仍需验收。

历史36命令timeout合同为19620+600=20220秒；当前policy新增P06原900/300/300秒三driver后，10个ready suite共39命令，串行timeout合计21120秒，另600秒上传余量，共21720秒=362分钟，尚未计setup。这是容量合同而非实测耗时；setup实际成本未知。保留YAML普通340/release360分钟均不满足此合同，不能仅enable、调到360或缩命令/预算恢复。两个CI容量test入口在暂停时如实SKIP，不得称PASS。本地原39命令、timeout和release missing保持；现行覆盖阈值见上节，历史strict100%报告不改写。容量及证据闭包由台账CI-3后续有限任务解决，不在本片新增分片工具。

## CI-2首片：coverage构建身份绑定（Refs #60）

本片目标待验证：每个新coverage run独立保存`coverage-image.id`，由本次`docker build --iidfile`写出；严格校验后按捕获的不可变ID inspect，再以同一ID执行JSON collect与LCOV export，包含无PhaseEvidence的直接调用。旧run/预存文件不覆盖；缺失/坏/多行ID、inspect失败或错配、任一命令失败均拒绝后续，不能fallback到可变tag。phases保存真实argv及其对应ID，不将仅记录tag的日志当执行身份证明。

A函数fixture、B适用engineering门禁、C独立真实daemon竞争/取消观测和D外层原900秒完整coverage均为合入前必要证据，结果见任务Issue/PR。本段先行描述工程合同，不预填PASS。C仅两微fixture/测试专用tag，10秒握手、每条30秒、整轮180秒含最多30秒owned-CID收尾；D必须经现有runner读取policy900秒约束，不以裸CLI冒限时。unknown CID/退出/残留保原件并停后续重任务交PM，不把宿主进程组停止当daemon回收。

首片不改普通cargo/M0消费者、target/计数目录、registry缓存、跨树锁或daemon监督；不开放并行重编译/coverage。完整源、未导入文件、JSON/LCOV分母、原参数/预算、Python80%/Rust100%和原21排除保持，失败/raw保留；CI仍暂停。本片不认证数据库system/release或其它CI-2能力。
