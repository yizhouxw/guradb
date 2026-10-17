# M0 单独复核记录

范围：从 `5596117798126153a7ed9cfef291824ff8096925` 开始的M0任务，覆盖6个Rust crate、API/manifest合同、构建、真实验收driver与harness/CI接线。作者在实现完成后另行进行差异审查；未使用第二位审查者，非外部独立背书。

## 已识别并修正

- 白名单必须逐层拒绝未支持SQL，不能把DataFusion SQL执行入口暴露给请求。实现使用AST→DataFrame；CTE/函数/表函数/副作用/事务/多语句等负例实际返回错误。
- JSON可选字段显式null原会被Serde当省略，与OpenAPI不一致。现要求省略或合法非空值；max_rows/timeout/view与manifest version_id均覆盖负例。
- 排队与执行之间有撤权窗口。增加取得执行槽后重新读取授权；真实S3暂停造成排队时撤销提交凭证的数据集权限，另一个同主体合法凭证观察任务明确失败forbidden，源读取未开始。
- 内存/结果不可只依赖LIMIT。加入完整对象/解码/有限DataFusion池/结果字节与句柄上限；超限无部分成功，取消终态不倒退，禁止spill。仍明确不是恶意文件硬RSS沙箱。
- 响应stats加入OpenAPI；实际HTTP成功句柄和分页按标准schema验证。PG初始化探针从临时unix服务改为最终TCP监听，避免重启窗口污染对照。
- 真实driver移动到functional、performance/component、faults/component对应目录；M0构建/fixture/锁文件变更触发运行时门禁。旧“planned应阻断”单测显式构造planned fixture，保留原断言，不因生产gate启用而删测试。
- 固定镜像、Cargo.lock及Python测试依赖；Actions保留只读权限/固定SHA/失败上传/原总预算约束。新M0远端运行尚未执行，不混用此前bootstrap首跑。

## 实际范围与剩余风险

初轮真实功能、组件性能和组件故障均已通过，最终结论以本任务最终提交后的harness report为准；中途失败日志保留在artifacts。功能包括PyArrow/PG18独立对照、S3版本读取、对象覆盖/删除、local symlink/损坏/schema拒绝、授权和分页、预算/TTL；故障包括排队/运行取消、执行点撤权、超时、恢复和进程重启。

性能是8192行/2文件的首次组件smoke，5个进程各cold/warm请求，逻辑GET和字节逐次精确核对，RSS/延迟按预冻结预算。没有此前基线，不自比较；不能据此推断海量数据、受控硬件产品性能或回归幅度。

local存在受信任文件系统下路径检查/读取的协作边界；Parquet与引擎同步批次不是任意CPU抢占。TTL按请求惰性清理，最大句柄容量始终有界；S3逻辑读取不包含SDK重试/wire计数。进程没有持久查询恢复；best-effort历史可能被源清理；无热刷新、Iceberg、索引、写入和分布式。

正常driver退出会清理本次容器/网络。Docker daemon资源不属于宿主子进程组，若宿主硬中断/强杀driver，需按trace中的随机`gura-*`资源名人工核对清理；不得批量删除其它任务资源。完整performance/stability/soak保持planned，release不得通过。上述限制与M0范围相符，无已知阻断最小闭环的未解决问题。
