# M1 操作与运行

先读 [范围与合同](m1-snapshot-serving.md)。Python3.11+，本地真实验证用Docker的PG18/SeaweedFS固定镜像；Python生产依赖和独立fixture工具通过锁安装。服务默认只监听loopback；其它部署的TLS、认证边界由操作者配置，未验收生产部署。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock -r requirements-m0.lock -r requirements-m1.lock
.venv/bin/python -m pip check
# 通过受保护环境注入连接信息；不要把真实DSN写入版本库/报告
export GURADB_PG_DSN='host=127.0.0.1 dbname=guradb user=operator'
.venv/bin/python scripts/m1.py init
.venv/bin/python scripts/m1.py register --config examples/m1/dataset.json
.venv/bin/python scripts/m1.py --root data/m1 snapshot --dataset 89b349e2-cc73-4c22-871d-c80a159d7789 --operation snapshot-001 --target examples/m1/target.json
# 使用上条输出的run UUID和已查询的epoch；首次为0
.venv/bin/python scripts/m1.py publish RUN_UUID --expected-epoch 0
.venv/bin/python scripts/m1.py grant --tenant demo --subject reader --dataset 89b349e2-cc73-4c22-871d-c80a159d7789 --token-sha256 TOKEN_SHA256
.venv/bin/python scripts/m1.py --root data/m1 serve
```

示例URI/摘要为占位，必须替换为真实源的canonical根和实际metadata/feature摘要、快照ID；[特征样例](../../examples/m1/features.json)展示规范logical_key编码、模型空间与媒体引用格式。S3构建增加 `--s3-endpoint`，并通过AWS环境变量配置凭据/region；凭据不进入dataset定义/feature/manifest。源码不会修改外部湖。

```sh
# GURADB_TOKEN由用户安全注入；CLI不读取PG或本地业务文件
.venv/bin/python clients/cli/m1.py describe 89b349e2-cc73-4c22-871d-c80a159d7789
.venv/bin/python clients/cli/m1.py search --dataset 89b349e2-cc73-4c22-871d-c80a159d7789 --query '{"text":"database","vector":[0,1],"model":"demo-v1","candidate_limit":100,"top_k":10}'
.venv/bin/python clients/cli/m1.py scan --dataset 89b349e2-cc73-4c22-871d-c80a159d7789
.venv/bin/python clients/cli/m1.py export --dataset 89b349e2-cc73-4c22-871d-c80a159d7789 --query '{"seed":"experiment-1","train_basis_points":8000}'
.venv/bin/python clients/cli/m1.py status JOB_UUID
.venv/bin/python clients/cli/m1.py cancel JOB_UUID
.venv/bin/python clients/cli/m1.py release JOB_UUID
```

作业接受后返回query_id和固定read_context；默认CLI等待，`--no-wait`只提交。每次POST创建新查询，网络错误不自动重试；客户端超时/中断请求取消。训练成功后用HTTP GET `/v1/jobs/<id>/parquet` 取Parquet，`/v1/jobs/<id>/objects/<sha256>`取所引用媒体，均带相同Bearer身份。release删除终态job及其结果并释放训练pin，此后返回404；release清文件后DB提交若失败，目录记录与pin保留，可重试release完成对账，但被明确释放的结果文件可能已不可取。不要提前释放仍在消费的训练manifest。scan/search默认有限结果，scan明确truncated；无M1分页，旧M0SQL分页仍沿用其原接口。

人工pin与GC：

```sh
.venv/bin/python scripts/m1.py pin RUN_UUID --owner training-experiment
.venv/bin/python scripts/m1.py unpin RUN_UUID --owner training-experiment
.venv/bin/python scripts/m1.py --root data/m1 gc OLD_RUN_UUID
```

GC拒绝当前published或任何pin，只删除本工具生成的旧run目录；不删除源湖。指定root必须与构建一致。PG历史run最多128，未提供PG历史清理/容量运维；达到上限应停止并规划下一版迁移，不能手动删约束过门禁。多个服务实例不能共享此单进程lease；DB重启导致连接失效后重启服务，遗留非终态作业明确失败，不透明重放。

M0互操作时使用生成的 `<root>/<run>/manifest.json` 及其实际SHA，按 [M0运行说明](m0-running.md)配置；容器需映射manifest中的本地绝对路径。该M0实例是固定启动清单，不自动跟随PG发布或复用PG grant。

真实验证：

```sh
.venv/bin/python scripts/cargo.py build --workspace --locked
.venv/bin/python scripts/m1_acceptance.py functional
.venv/bin/python scripts/m1_acceptance.py performance-smoke
.venv/bin/python scripts/m1_acceptance.py stability-component
.venv/bin/python scripts/harness.py check
```

测试只创建随机命名的本任务容器/网络并在finally清理。硬杀driver可能留下Docker资源，按trace逐项核对，禁止批量清其它任务。完整release仍缺完整performance/stability/soak，不能宣称可发布。备份需要PG目录与完整data/m1及训练结果一致副本；本地Git checkpoint只恢复代码。
