# A0 synthetic P0 组件负载合同 v1

状态：冻结输入与独立真值；首次运行只产出候选结果。没有获准业务数据，**不是业务
baseline、完整性能或 soak**。依据[下一阶段 A0](../plans/2026-10-18-next-stage.md)
和[证据协议](../../harness/evidence.md)，实施范围见[变更计划](a0-workload-change-plan.md)。

## 固定输入与支持边界

`scripts/p0lib/contract.py` 定义 `a0-synthetic-p0-v1`，输入/查询/driver 内容摘要写入每次
result；`inputs/trace.json` 保存全部源行、向量、关系与各发布视图，不依赖业务数据。

| 项目 | 固定合同 |
| --- | --- |
| 源/规模 | 本机托管 Iceberg v2，初始256行，每批16行；原256条数据保留 |
| 文本 | 四种 ASCII 标题按ID模4重复，0–16 UTF-8字节；统计包含NULL空文档 |
| NULL | 初始0个；新增每16行的第1行title=NULL、第2行active=NULL |
| 键 | int64 ID从0递增，NULL键/重复键拒绝；边界大整数由oracle合同测试覆盖 |
| 向量 | seed17，CPython Random均匀[-1,1)，16维，identity-v1，squared-L2；模型m2-test-17 |
| ANN | 4 partitions / 4 probes，候选100、Top10；与穷举真值完全一致，不降低原recall要求 |
| 分布/过滤 | 重复标题与active相关；初始active=true为1/2、title=beta为1/4，NULL选择率0；每版记录实际计数 |
| 媒体 | 此P0输入0对象/0字节，不证明媒体吞吐；oracle小fixture校验非空media引用对齐 |
| Graph | 保留60条typed-edge，source=i%10、target=(i+1)%13、偶数link；seeds0/2一跳 |
| 并发 | 两个前台请求、一个append/refresh/publish线程，每个job三个同机worker；支持local/loopback HTTP |
| 预算 | 请求<=10000ms、coordinator及每worker RSS<=512MiB；仍受writer32批/10000行及目录128 run保护 |

每轮保留旧六类请求（融合/训练、ANN/图、全文/scan），追加过滤融合、全文等值过滤、
NULL过滤精确向量、active=false精确向量。查询 JSON 与摘要保存在合同中，不以减少查询、
样本或旧数据换取绿色。NULL、重复、同分、过滤偏斜和漏重的独立小fixture不是业务代表性证明。

## 真值与持续窗口

标准库 `SourceOracle` 从写入前源行和显式特征输入建立预期，不能导入生产 search、
samples_for 或 BM25。BM25按全库N/df/长度计算 k1=1.2、b=.75，统计后过滤；精确L2
穷举，分别截断全局候选窗口再按RRF k=60融合，稳定逻辑键打破同分。训练按canonical
JSON身份/seed的SHA256前64位模10000分split；逐样本核对ID/version/值/向量/media。
run的opaque revision/view作为显式输入绑定，核对run ID与source snapshot/metadata/features
摘要；旧记录版本由先前源输入oracle继承，不从新bundle行推导预期。
响应须与受理句柄context一致，不能用响应自行选择另一已知视图的oracle；新增记录不能复用
历史revision。默认最新发布的选择时刻未单独认证，不把固定视图一致性扩大为新鲜度保证。

`duration=0` 保留调用者1..8次更新，明确不证明持续写入。`duration>0` 将updates解释为
最低次数，并固定至少8次（现有CLI最大8，因此实际8）；时点为窗口5%至90%等距，60秒
窗口为3、10.286、17.571、24.857、32.143、39.429、46.714、54秒。这是新负载版本，
不能与旧两次append结果当同负载比较。60秒末384行、9个源批次、10个目录run（含图），
没有扩大生产常量。延长duration会拉长间隔，不自动成为高频写入或长稳证明。

真实trace保存scheduled/started/committed/published时点、view/epoch、累计行数、构建
source reads/bytes、保留build/source字节增长。append及publish必须覆盖窗口四个四分位，
迟到超过一个间隔、publish越界或缺少整段读取失败；不会在窗口末突发补齐。每段读取只计
完整落在窗口内的请求，尾部跨界round单列。拒绝测试覆盖当前32批/10000行/128 run容量。

## 测量、原始证据及局限

仍通过 `scripts/p0_acceptance.py` 运行；无需新入口或更改 policy。例：
`.venv/bin/python scripts/p0_acceptance.py --transport http --duration 60 --run-dir artifacts/p0-a0-<unique>`。
并行A0任务的该命令、harness check及提交hook必须由共同Git目录下
`guradb/coordination/a0-heavy-gates.lock` 的fcntl.flock包裹整个命令/子进程。

每次结果记录机器/OS/Python/全部依赖锁、组件查询延迟、协调器及worker RSS、worker work、
source/artifact请求与字节、构建及历史大小。`responses.log` 在真值断言前保存完整响应与输入，
`requests.log` 保存核验后的指标和响应摘要（空集合不伪记recall@10为1），
`inputs/trace.json` 保存独立源真值输入，根 `trace.json` 保存真实发布事件；既有v2归档会
保全 result、全部trace.json及.log，manifest逐文件摘要可复核。每次运行单独目录，失败保留。

source为本地文件，因此没有远端S3 GET/HEAD测量；source/artifact计数不等于HTTP wire bytes。
训练公开manifest不包含协调器I/O计数，明确标记缺失；worker work证据仍逐项保留。
OS缓存不受控，真冷、受控热、部分命中、超过总缓存全部为not_run；native子进程完整峰值
RSS、五次独立受控重复、完整性能/stability/soak继续缺失。首次候选不能自比较成性能回归
通过，也不能把本片通过宣称A4或发布通过。M0/M1/M2原有8192行组件测量和预算保持不变。
