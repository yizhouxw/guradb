# M2 与本地三 worker 操作

继承 [M1 初始化/授权/固定 Snapshot](m1-running.md)。安装 `requirements-dev.lock`、`requirements-m0.lock` 和更新后的 `requirements-m1.lock`。
本轮能力是有界 alpha；不意味着完整 M2/M3 或生产发布。

## ANN 与 Graph

在已有 Snapshot target JSON 添加 `"ann":{"partitions":8}`，需要至少128行，正常 snapshot/publish 后可查询：

```sh
.venv/bin/python clients/cli/m1.py search --dataset "$DATASET" \
  --query '{"vector":[0,0],"model":"test-space-v1","vector_index":"ann","nprobes":8,"top_k":10,"candidate_limit":100}'
.venv/bin/python clients/cli/m1.py graph --dataset "$EDGES" \
  --query '{"source_field":"source","target_field":"target","type_field":"kind","seeds":["1"],"type":"link","direction":"out","max_edges":100,"max_fanout":100}'
```

模型和维数必须匹配实际 features。Graph 源是有上述三列的同视图边表；不跨外部节点表解析。
详情见 [ANN](m2-ann.md)、[Graph](m2-graph.md)。

## 显式 append 刷新

```sh
.venv/bin/python scripts/m1.py --root data/builds refresh --dataset "$DATASET" --operation append-001 --target next-target.json
.venv/bin/python scripts/m1.py progress "$RUN"
.venv/bin/python scripts/m1.py publish "$RUN" --expected-epoch 1
```

它验证完整 append 历史后全量重读并重建索引，尚无只读取新增文件的 delta 执行；不会把更新/删除/rewrite当作append。
未知结果先查询 run/operation；同operation不同target拒绝。详情见 [增量合同](m2-incremental.md)。

## 托管 append

```sh
.venv/bin/python scripts/m1.py --root data/managed managed-init --name documents
.venv/bin/python scripts/m1.py --root data/managed append --name documents --operation batch-001 --rows batch.json
```

rows 文件为固定 `[{"id":1,"title":"first","active":true}]`。单机可信操作者、独占本地目录，不能用此入口写回外部湖。
返回固定 source snapshot/metadata；生成完整 features 后，在其根目录登记独立数据集，使用普通 snapshot/publish 服务化。
源已提交与索引已发布是两个状态；失败不得通过重新命名 operation 盲目重发。详情见 [writer](m2-writer.md)。

## 三 worker 与 MCP

```sh
.venv/bin/python scripts/m1.py --root data/serving serve --workers 3
GURADB_URL=http://127.0.0.1:8081 .venv/bin/python -m clients.mcp.server
```

token 使用已有 `GURADB_TOKEN` 环境变量。三 worker 返回各 PID、分片和实际记录数；精确向量/scan/Graph/训练转换分担记录，全文统计与ANN仍协调器执行。
详见 [本地运行时边界](m3-local-workers.md)、[MCP说明](../../clients/mcp/README.md)。所有入口仍由HTTP授权、固定view、job生命周期控制。

## 验证与兼容

```sh
.venv/bin/python scripts/m2_acceptance.py functional
.venv/bin/python scripts/m2_acceptance.py performance-smoke
.venv/bin/python scripts/m2_acceptance.py stability-component
.venv/bin/python scripts/harness.py check
```

旧M1 bundle继续支持exact；ANN只在新目标显式启用，新索引不是独立事实源。原M1目录schema不变；托管writer显式初始化独立gura_managed表。
新服务的job kind增加graph；回退旧服务前先排空新作业。新ANN view应保留新服务读取，回退到旧binary前显式选择旧view；不要删除仍被pin/源快照引用的产物。
本地原始证据在artifacts，最终报告按commit归档；不自动推送。完整performance/stability/soak与HA/跨机/升级仍不通过。
