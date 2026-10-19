# 使用指南

本页是当前alpha命令速查。完整概念与任务分别见[接入](ingestion.md)、[混合检索](retrieval.md)、[训练数据](training.md)和[接口参考](reference.md)；这些指南会明确标注尚待实现的产品流程。

## SQL 与接口选择

M0 HTTP SQL 使用固定 manifest。请求有 sql、parameters，返回异步 query_id，随后查询状态、取分页结果或 DELETE 请求取消。结果和 read_context 绑定启动视图，游标不能跨查询/身份使用。入门请求见[安装部署](installation.md)，完整字段见[M0 OpenAPI](../../api/http/openapi.json)。业务参数使用绑定值；int8 超出客户端安全整数范围时使用 `{"type":"int8","value":"9223372036854775807"}`。

可选 PG SQL 端口复用 M0 执行白名单，支持有限 simple/extended prepared 查询。Psycopg 必须 `autocommit=True`，数据库名 `guradb`，user 对应 principal_id，password 是原始 token。PG 行结果不携带 HTTP read_context；不要把内部控制 PG 当查询入口。可运行 SDK 例子见[PG 端口指南](../design/pg-wire-running.md)。

## 检索、扫描和 Graph

下列 CLI 连接 M1/M2 HTTP，默认 URL 为本机服务；由操作者通过环境注入 `GURADB_TOKEN`，需要时在子命令前传 `--url http://127.0.0.1:8081`。先按[M1 操作](../design/m1-running.md)完成登记/构建/发布/grant。`DATASET` 必须是自己已授权的数据集 UUID，示例模型和向量必须替换为该数据集实际特征。

```sh
.venv/bin/python clients/cli/m1.py describe "$DATASET"
.venv/bin/python clients/cli/m1.py search --dataset "$DATASET" \
  --query '{"text":"database","vector":[0,1],"model":"demo-v1","candidate_limit":100,"top_k":10}'
.venv/bin/python clients/cli/m1.py scan --dataset "$DATASET"
```

describe 返回 schema/model/read_context；search 返回固定视图下候选窗口内的排名，不是任意 SQL。模型/维数不符必须失败。scan 有结果上限和 truncated 标记，当前无 M1 分页或 scan 条件/投影，不能把它当全量导出接口。

ANN 需在构建 target 中显式启用、满足构建行数等条件，查询再指定 `vector_index=ann` 与 nprobes；未构建不能默认可用。Graph 使用同视图的边数据集，指定 source/target/type 列、seeds、方向及扇出预算。配置和完整请求见[M2 操作](../design/m2-running.md)，不支持跨表节点解析或多跳。

## 训练导出与结果生命周期

```sh
.venv/bin/python clients/cli/m1.py export --dataset "$DATASET" \
  --query '{"seed":"experiment-1","train_basis_points":8000}'
.venv/bin/python clients/cli/m1.py status JOB_UUID
```

把 JOB_UUID 替换为实际 job id。CLI 默认等待，`--no-wait` 只提交。导出覆盖固定视图的全部记录，seed 和 train_basis_points 产生可复现 split 标签，8000 不意味着只导出 80% 的记录；不支持用户样本过滤。成功后按[M1 OpenAPI](../../api/http/m1-openapi.json)下载 `/v1/jobs/<id>/parquet` 和 `/v1/jobs/<id>/objects/<sha256>`，均使用相同身份。

```sh
.venv/bin/python clients/cli/m1.py cancel JOB_UUID
# 仅在消费完成且不再需要结果时执行：
.venv/bin/python clients/cli/m1.py release JOB_UUID
```

cancel 请求停止作业；release 删除终态 job/结果并释放训练 pin，此后访问为 404。下载完成和使用者停止引用后才能 release。若 release 清文件后 DB 提交失败，应重试同 job 的 release 对账，不能保证已释放结果仍可下载。

每次提交查询/job 的 POST 都创建新请求，网络失败不要盲目重发；已取得 query/job id 时先查询状态。源构建/发布操作有单独 operation/CAS 语义，见[运维管理](operations.md)。客户端取消、超时或收到失败结果时，必须将本次不完整输出视为失败。
