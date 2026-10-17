# 派生索引丢失后的本地重建

用户验收：已发布视图的 BM25、Tantivy、ANN 或 serving shard 文件丢失时，旧请求明确失败；操作者显式创建新 operation，从托管事实副本重建新 ready run，独立 CAS 发布。源湖已过期或删除不影响这个恢复路径。新视图保留 data_revision_id、source_versions 和逐记录 record_version，仅更新 read_view_id 与 index_versions。读取 bundle v1/v2，重建产物统一为 v2；旧 v1 的 Tantivy 评分迁入版本化 BM25 global-v2，不承诺旧评分数值不变，旧 binary 必须明确拒绝 v2。

## 变更计划与白名单

不变量 INV-001/003/007/008/010/011/012：事实/特征/媒体仍唯一权威，重建不能接受事实损坏、变更记录版本或原地修改 published bundle。最小切片是单机可信操作者入口 `modules.query.rebuild.rebuild(control, dataset, operation, root)`，不改变持久 schema，不读取外部源，不恢复丢失的事实。源事实副本、bundle 或 manifest 丢失/摘要不符时明确失败；不是从损坏索引推测事实。

验证 bundle SHA、全部 source dependency 副本、manifest 引用与每个 Parquet fragment SHA/大小/schema/完整逻辑键和值；同时验证媒体副本。仅旧派生索引文件检查被跳过。新 run 独立复制全部事实与媒体并重新生成 BM25、Tantivy、可选 ANN 和三个 serving shards，旧 run GC 不得影响它。保持 32 文件、10000 行、32 MiB 压缩事实、64 MiB decoded 行及既有产物/时间预算，不宣称提速。

## 操作与恢复

调用 `rebuild(control, dataset, operation, root)` 返回 ready run；仍通过现有 `publish(control, run_id, expected_epoch)` 发布。未发布前 published 指针保持旧值；generation/epoch CAS 拒绝旧构建覆盖新提交。应保留旧训练 pin，直至使用者显式释放。重建只对当前 published view；不接受调用方另传源 URI、索引目录或业务行。

同 operation 重放返回原 run，ready/published/failed/building 都不自动重试或换基点；与其它 operation 类型复用同 ID 拒绝。进程中断保留 building 及现场，需诊断后使用新 operation。构建期间对原 run 持有 pin；新 run 所有引用归入自身目录。失败不清除旧 pin，不修改原 bundle，不自动发布或删除现场。

## 证据与局限

`tests/functional/rebuild.py` 使用真实 PG 与独立 PyIceberg fixture，删除全部旧派生索引和外部源，再验证重建、operation 重放、CAS、精确/全探针 ANN、全文、训练版本一致性和旧 run GC 后独立读取；损坏事实拒绝并保留失败 operation。该组件恢复不等于在线自愈、跨机 DR、通用 schema/模型迁移或完整生产发布。新 ANN 仍为近似索引；全探针固定用例的一致性不替代通用 recall 验收。

## 操作入口

```sh
.venv/bin/python scripts/m1.py --root data/builds rebuild-indexes --dataset "$DATASET" --operation rebuild-001
.venv/bin/python scripts/m1.py publish "$RUN" --expected-epoch 1
.venv/bin/python scripts/local_acceptance.py rebuild
```

重建只生成ready候选；发布仍需独立CAS。返回结果未知时按相同operation对账，不重新命名操作。
