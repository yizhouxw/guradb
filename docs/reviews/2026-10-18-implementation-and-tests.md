# 实现与测试复审

日期：2026-10-18；覆盖率门禁于2026-10-19按用户授权更新。起始主线 `070299106d609582a25363604928643bb728634a`，工作区干净；任务 `docs-test-coverage`。本页更新当前状态，历史A0/PG报告保留其原commit身份。

## 对账结论与修正

- PG wire 首片已合入main：Rust M0同一manifest/只读执行器，loopback、非TLS、autocommit，已含真实Psycopg 3.2.10、psql18和raw协议driver。把计划中的笼统“PG wire暂缓”修正为后续TLS/目录/更多驱动暂缓；路线图标题更新为已合入。
- M0 HTTP与PG SQL入口共享SQL白名单和授权，但HTTP int8为字符串、PG为整数，PG行结果没有HTTP read_context。新增同场景比较按合同归一化，不要求两个接口字节相同。
- M1/M2仍是Python/PyArrow published-view job服务；检索/训练/Graph尚未统一SQL。A1样本选择、A2按需读取、A3历史生命周期及A4质量/成本缺口均未因此完成。
- README将已经落地的M2有界切片从“后续实现”改为当前实现。原2026-10-18能力复审明确标为历史基点，并链接本次更新；不把历史性能测量改绑新源码。
- 测试原先缺覆盖率统计。Python必须显式纳入namespace目录及未导入文件；只统计已导入文件会虚高。单元/组件契约覆盖率、真实接口场景、性能/故障各自报告。

## 新验收与实测状态

目标：全部生产源纳入统计，适用源码行覆盖率严格100%（Rust精确排除项及原始数值单列）；HTTP与Psycopg SQL场景同时覆盖M0白名单。具体范围、风险和恢复点见[变更计划](../design/test-coverage-change-plan.md)，命令见[测试入口](../../tests/README.md)。

初始Python完整分母2926行，覆盖1320行（45.112782%）；仅已导入文件的77.889151%不能作为全项目基线。Rust初始LLVM报告为703/2599（27.048865%，当时同文件内含单元代码）；本轮将已有Rust单元代码原样移至测试目录，后续单列生产源，二者分母不能当同口径性能趋势比较。

新增双接口场景首次实跑：15种查询、7种参数、17种拒绝及撤权/恢复，62项比较通过，Psycopg3.2.10文本/二进制和prepared，独立PG18真值；日志`artifacts/coverage-baseline/interface-scenarios.log`。这不替代最终commit的完整门禁。

Python单元/组件契约集合已达到2926/2926行（100%，零排除），原始报告`artifacts/coverage-python-7/python.json`。Rust补测后原生LLVM为2396/2449；以唯一可执行源码行计为2243/2264，排除21行后2243/2243；原始报告`artifacts/coverage-exclusions-raw/`。原生汇总与DA源码行分母不同，不能直接相减；后者以外的闭包/分支执行仍是独立验证义务。该局部报告期间有并行文档变化，身份失效，最终检查须重跑。稳定工作区报告见下文；最终提交身份与任务receipt由提交后检查保存，不把此工作区报告改绑未来commit。完整performance/stability/soak仍planned，远端CI尚未验证，未推送。

## 复核与限制

严格门禁按整数缺行判断，未导入Python文件、未出现在LLVM中的Rust源、显示值四舍五入为100%但仍缺行、测试失败均有拒绝用例。unit-coverage进入变更选择和release，不用“工具可执行ready”代表覆盖率目标通过。

测试补强修复预先取消读取的竞态；启动argv仅改为私有函数显式输入，稳定键长度转换抽成可直接验证的边界。未改变持久布局、对外接口、检索质量/工作负载/性能阈值。测试中使用可信合成数据；单元边界fake不证明PG锁/SQL事务，真实driver继续独立执行。

2026-10-19按用户补充要求采用有限排除，清单逐行说明原因和替代证据并绑定源码SHA；不宣称无豁免全项目100%。可直接测试的SQL、路径、队列和授权缺口已补测。依据根AGENTS的“有限切片通过门禁和复核后提交”，整项验证与提交仍待最终检查，不绕过hook。最新整项报告位于`artifacts/harness/`，最终状态以报告的commit/checkout及task-status为准。

本轮模块导航复核还修正了catalog/query/index、模块地图和CLI的“未实现/尚无内核”旧文字，明确各自已落地切片及长期职责。M0历史计划依据本地completed receipt更新状态；ADR0005和CI预算说明补当前状态，保留历史证据身份。

首轮整项报告`artifacts/harness/20261018T132612Z-75f4c19d/report.json`绑定当时完整工作区，contracts/9个functional driver/harness-tests/performance-smoke/policy/repository/rust通过，stability-component及unit-coverage失败；后续源码修正后不能复用其指纹作为最终报告。M0故障场景在授权恢复后立即读取失败，原断言未记录响应体，不能断言具体错误码；已将正常授权写入统一到既有原子replace+容器内SHA可见性fence，保留拒绝/恢复断言并增加失败响应证据。针对性M0/PG组件故障实跑修复通过（`artifacts/coverage-stability-repair/result.json`），不重试SQL或放宽业务预算。

排除检查器与选择逻辑已自测：剩余未豁免缺行阻断，源码SHA/原文/类别/范围/重复/缺理由均拒绝；所有源码文件仍必须出现。初次补测的Bind格式错误预期误写为invalid_parameter，实际协议合同为protocol_violation，已修正测试断言，不改生产错误分类。当前远端CI和完整发布实验未运行。

## 稳定工作区收口

`artifacts/harness/20261019T000855Z-8802fb7c/report.json`九组change门禁全部passed，覆盖任务原始base `070299106d609582a25363604928643bb728634a`，检查期间源码未变。已核对每条命令日志SHA和当前checkout指纹；Python2926/2926、零排除，Rust源码行2243/2264、排除21行后2243/2243，LLVM原生2396/2449。共用HTTP/Psycopg场景62项比较通过；不将原生函数/闭包缺口改称全部生产代码100%。

用户文档任务已完成，按用户授权复核纳入同次本地提交；安装页SHA匹配其真实HTTP示例，12个能力域、两条执行路径、身份/预算/恢复边界和文档先行流程均已核对。修正POST重试的表述，补充开发页覆盖率排除范围。本次无持久格式或API变更；取消入口拒绝预先取消是既有合同缺陷修复。最终commit/checkpoint/receipt以提交后整项check为准，尚无远端CI或生产发布证据。
