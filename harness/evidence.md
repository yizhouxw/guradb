# 性能与稳定性证据协议 v1

状态：校验工具可运行，真实数据库 driver 与 baseline 尚不存在。测试中的数值/trace 仅验证 harness，不代表产品结果。

本页的严格 JSON 协议用于完整 workload/fault registry。首次组件门禁采用[接入清单](runtime-onboarding.md)中的真实局部测量/故障日志及预冻结预算，单独标明验证边界；它不向全库校验器提交缺项子集，也不被记录为全库通过。首次无旧基线只建立实测候选，不自比较；完整产品发布仍需本页协议及全部场景。

## 公共头

性能和稳定性输入都是 JSON 对象，以下字段必需：

| 字段 | 约束 |
| --- | --- |
| `schema_version` | 整数 1 |
| `kind` | `performance` 或 `stability` |
| `provenance` | `engine`；拒绝 synthetic/demo |
| `git_commit` | 精确 40/64 位 Git hash |
| `checkout_digest` | 本次源码/配置快照 SHA-256，不能只用可能 dirty 的 commit |
| `dependency_lock_digest` | 依赖锁文件 SHA-256；可作为本次变更的一部分与 baseline 不同 |
| `workload_digest` | driver、查询、生成/过滤/索引与预算设置的整体 SHA-256 |
| `dataset_digest` | 固定数据/样本清单及源版本的整体 SHA-256 |
| `environment` | 非空 fingerprint 字符串：hardware、os、toolchain、topology、object_store；勿包含凭证 |
| `correctness_passed` | 必须为 true，由同次实际功能/真值校验产生 |

头部是证据契约，不是信任证明：校验器无法判断某个外部报告是否诚实。driver、数据清单、日志和原始测量需保留并复核；不得手填性能结果充当真实 baseline。

## 性能报告

增加 `workload_id`、`parameters`、`metrics`。workload 必须登记于 [workloads.toml](workloads.toml)。

`parameters` 至少包含 `cache_mode`（cold/warm/partial/over-capacity）、正整数 `concurrency`、整数 `seed`；driver 必须同时记录读视图/新鲜度、向量空间/维度、索引参数、过滤选择性、Top-K/候选预算、后台负载与数据规模等实际因素，不使用隐藏默认值。

`metrics` 的键必须精确等于 workload 指定集合。每项是至少 5 次独立运行的数值数组，不是把一次请求的 5 个点假称为重复实验。`latency_p95_ms`/p99 每个样本是一次充分请求测量的分位数；原始分布和测量窗口放在附件，比较器不负责采样。

```sh
.venv/bin/python scripts/harness.py compare-performance \
  --baseline artifacts/bench/baseline.json \
  --candidate artifacts/bench/candidate.json
```

比较要求 workload/dataset digest、全部 environment 和 parameters 相同。code/checkout/依赖锁可以不同，它们是待评估的变更；工具链/机器/拓扑变化则需要独立受控实验，不与代码回归结果混用。

延迟/成本默认比较重复运行中位数；recall 使用最差一次，防止中位数掩盖质量下降。相对回退预算见 registry；重复数据 `(max-min)/median` 超过 30% 判为不可判断并失败，不把噪声结果记为通过。零成本 baseline 变成正成本按回退处理。

缺指标、样本不足、NaN/Infinity/bool、负数、非法 recall、不同缓存/环境均失败。单位在 registry 中固定，driver 不得换单位。同等声明上下文并不能排除未记录的混杂因素，需真实受控 runner 与审查。

基线必须来自可复现的实际提交和校验过的工作负载，首次建立时连同原始结果、硬件/缓存控制、绝对预算和构建成本记录；更新需保留前后比较及理由。当前不提交任何虚假 baseline，也不以共享 CI runner 数值替代稳定实验环境。

## 稳定性报告

增加 `suite_id=lake-publication-recovery`，以及完整的 `scenarios` 数组，每个 ID 对应 [faults.toml](faults.toml)。每项记录：

- `id`、整数 `seed`、达到场景要求的 `workers`。
- `fault_injected=true`、`passed=true`，来自 driver 的实际操作和观察。
- `checks`：该场景所要求的不变量 ID 到布尔结果的映射，必须全部 true。
- `trace`：相对报告目录的非空日志文件；`trace_sha256` 必须与内容匹配，不能引用外部路径。

```sh
.venv/bin/python scripts/harness.py verify-stability \
  --report artifacts/faults/report.json
```

禁止缺场景、重复 ID、跳过故障、缺 seed、伪装单 worker 为集群或仅有无内容 trace。trace 摘要只能发现文件变化，不能代替事件语义判定；需要 driver 断言及独立复核关键提交/恢复轨迹。

## 执行报告与退出码

`check` 在独立 run 目录中写 `report.json` 和各命令日志，包含选择依据、commit/checkout digest、状态、耗时和未实现 suite。原始日志不可因失败被覆盖；检查途中源码/配置变化会使结果失效。

check 报告还保存实际 selection_base、每条命令的 argv/退出码与 log_sha256，HEAD 变化也使证据失效。checkpoint/task-finish 按当前 policy 重算范围，核对完整 suites/commands 及日志；成功后归档 report、日志和路径映射，见[开发流程](development-workflow.md)。本地任务完成必须覆盖起始 base，不能以提交后空差异或 bootstrap 报告结项；旧报告缺新增字段时重新测量。

退出码：0 = 指定范围的门禁通过；1 = 回归/失败/缺失必需 suite；2 = 策略/输入/前置条件不合法或结果不可比较。bootstrap 的 0 不能用于宣称数据库正确、性能合格、稳定或可发布。

命令通过 argv 执行，无隐式 shell。超时、退出失败、缺工具和超量输出有独立状态；POSIX 下结束子进程组。非 POSIX 的后代进程清理能力有限，目标 CI 为 Linux；真实 driver 仍需释放端口、worker、临时 bucket 前缀和租约。
