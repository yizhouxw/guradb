# ADR 0015：可审计行覆盖门禁与双接口场景

- 状态：已采用；适用源码行100%，审查后的排除项单列
- 日期：2026-10-18；2026-10-19按用户补充要求采用有限排除
- 依据：用户要求修正当前文档/计划、单元测试行覆盖率100%、场景同时覆盖HTTP及PG Python SDK SQL
- 关联：[质量门禁](0005-agent-harness-and-quality-gates.md)、[PG端口](0014-bounded-pg-wire.md)、[变更计划](../design/test-coverage-change-plan.md)、[测试入口](../../tests/README.md)

## 决定

Python对modules/clients全部生产源统计coverage.py行覆盖率，包含namespace和未导入模块；当前不允许Python行排除。Rust对crates各src生产源运行cargo-llvm-cov，门禁统计LCOV DA记录的唯一可执行源码行。LLVM原生LF/LH和JSON汇总还会分别计入部分嵌套函数/闭包映射，故单独保存，不能将DA排除数直接从原生分母扣除。目标按适用行缺行整数严格为零；缺工具、缺文件、失败和源码身份变化均拒绝，不依赖显示百分比四舍五入。已有Rust单元代码原样迁到测试目录。

按2026-10-19用户授权，[排除清单](../../harness/coverage-exclusions.json)只接受具体行，类别限于解析器不变量、底层库不变量、难以稳定注入的操作系统/随机边界和LLVM映射闭合符。每项记录完整源文件SHA-256、行号和原文、原因及替代测试/上游约束证据；文件改变、原文不符、缺失依据、重复、非可执行行、glob/范围排除均拒绝。LLVM映射类别只接受闭合符，不能包裹业务语句。排除清单或检查器修改也触发unit-coverage及harness自测。

原始JSON/LCOV保持不变，报告同时列原始源码行、排除行（含本轮已覆盖的排除行）、适用行、逐文件缺行和LLVM原生汇总。100%指排除后适用源码行，不能写成全部生产代码无豁免覆盖，也不证明每个内联闭包或分支均执行。新增排除须按门禁变更复核，优先补可测业务与负例，不因测试失败自动扩大清单。

Python当前运行单元及既有组件契约集合，Rust运行workspace单元；不合并真实HTTP/SQL功能、性能或故障场景到单元覆盖率。开发工具脚本继续单独harness自测。必须同时报告测试集合边界，不能把组件参与的集合称为纯隔离单元测试，也不能从行覆盖推导分支、故障或产品质量完整。

使用固定coverage.py 7.11.0、Rust1.90.0/LLVM及cargo-llvm-cov0.6.21；开发依赖与数据库生产依赖分开。unit-coverage进入运行时代码、单元/契约测试、覆盖率工具/配置等变更和release选择。suite的ready表示命令真实可运行，任何未豁免缺行仍使检查失败；不关闭hook提交。

M0同一manifest的场景清单同时经HTTP和真实Psycopg3.2.10 text/binary/prepared运行，使用PG18独立真值；按合同将HTTP int8字符串与PG整数归一化，保留bool/NULL。覆盖正常查询、参数、拒绝、撤权及恢复；原有分页、取消、容量、畸形协议、预算、S3和组件故障测试保留。

M1/M2检索、Graph和训练仍通过其HTTP/CLI/MCP合同验证。PG wire首片只支持M0白名单，不因场景矩阵要求虚构或扩展SQL能力；执行面统一属于后续产品切片。

## 限制与验收

100%行覆盖不能取代独立真值、负例、不变量、检索质量和性能/恢复证据。任何未豁免缺行继续阻断；不通过删测试、批量排除模块、减小输入或放松业务预算达标。最新数值、失败与未完成项见[实现复审](../reviews/2026-10-18-implementation-and-tests.md)，最终提交与checkpoint须等待整项目标及门禁通过。完整performance/stability/soak、远端CI和生产发布维持原缺口。
