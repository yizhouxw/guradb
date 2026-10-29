# 受控固定读取核心切片

B=a7e49aa3bc09e10eac538a86fd31bf307477c8f4；分支 codex/fixed-read-core-20261029，独占 worktree /Users/chad/dev/guradb-fixed-read-core-20261029；receipt c2d5b1fc438441dca70f7c70ebfb7543。仅受控本地 best-effort 源，不实现 P08 正式目录入口。

先行合同：docs/user/controlled-fixed-read.md，2026-10-29 08:09前（行为代码尚未更改）。最小变更：新固定请求协议→复用唯一 SQL prepare/execute→全源稳定键验证→附带固定身份/行血缘。关联 ADR0004/0016/0027、数据合同稳定ID/版本。manifest与文件摘要是唯一版本权威，auth_file为调用者身份/最小权限来源，SQL不控制文件路径。

对象由操作者创建/保留；Catalog持有固定manifest，服务进程持有Catalog。QueryRegistry持有有限句柄/结果，query task持有source/Arrow/DataFusion和semaphore许可；成功/失败释放任务资源，结果按retention回收。无目录pin/lease、无源写入，无迁移/外部提交副作用。

| 场景 | 真值与验证 | 状态 |
| --- | --- | --- |
| C1 显式dataset/revision/view、过滤投影排序LIMIT | 独立Python fixture预期，真实HTTP/Rust/DataFusion，含完整int8/NULL与行血缘 | 作者及非作者真实用例通过；最终commit由receipt绑定 |
| C2 错版本、unsupported、越权/预算、缺对象或摘要变化 | 实际HTTP错误且无结果、无latest/legacy | 作者及非作者真实用例通过；最终commit由receipt绑定 |
| C3 完整性失败后释放 | 单并发单句柄配置，失败终态，文件FD/下一次有效请求及retention回收 | 作者及非作者真实用例通过；最终commit由receipt绑定 |
| C4 兼容旧入口 | 同服务 `/v1/queries` 原协议真实查询 | 作者及非作者真实用例通过；最终commit由receipt绑定 |

资源预算沿用M0更小值；稳定键索引只借用执行池预算且先释放。测试使用明确synthetic fixture，不做业务/性能/规模结论。scripts/fixed_read_core_acceptance.py构建并启动真实Rust容器，仅本机隔离文件/端口；需要Python PyArrow用于fixture与HTTP验收，不是在线内核。

阶段适配真实阻断正常hook；有界development/core_gate子实例单写harness选择/报告及tests，最终整体复核。强化/发布与旧失败保留。非作者system-test后审本精确候选及适配；禁止跳hook。失败保留artifacts，必要在新目录从checkpoint恢复，不覆盖旧dirty。

独立验收由非作者system-test实例01a18501-4ab0-7eb0-b968-48391b48ecfb执行，6行/2036bytes/两fragment的独立字面真值通过。发现新OpenAPI示例沿用legacy以及driver错误HTTP码均已闭合；Docker行政发布auth_file的原子替换+容器可见确认已纳入手册/driver。两次未完成该发布前提的503失败保留，不以重试HTTP洗绿。
