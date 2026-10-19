# 准备与消费训练数据集

状态：完整选样/关联/批次读取待实现；当前仅固定视图全记录导出与确定性 split，无 DataLoader、随机混洗或 checkpoint/epoch 恢复。

## 先定义训练集

复现需要源视图、选样条件、样本身份、模态/标签/特征映射、划分、处理版本和保留期限。Parquet 只是输出格式，生成成功不证明样本选择或读取正确。

例如一个检修样本含图像区域、文字、设备标签和特征；缺图/缺标签时拒绝还是保留缺失必须声明。同一资料片段分到训练和验证两边可能泄漏，按父资产/实体分组划分是目标要求，当前不支持，须外部准备并记录。

## 目标工作流

1. 选择固定 view 和保留等级，确认媒体与必要特征可取。
2. 同语义查询过滤/投影并关联标签/模态，检查数量、分布、重复与 NULL。
3. 选择 split、seed、分组/去重，保存规则版本。
4. 建 manifest 与 pin，记录样本 ID/version、对象、模型、schema。
5. 导出或批次消费，核对 worker 覆盖、不丢不重和恢复；结束后释放。

新发布不改变已受理训练任务；撤权对后续受控读取生效。取消/重试不留无主 pin。完整工作流尚待实现，不是当前可执行教程。

## 当前全视图导出

完成发布/授权，提供实际 `DATASET`、`GURADB_TOKEN`：

```sh
.venv/bin/python clients/cli/m1.py export --dataset "$DATASET" \
  --query '{"seed":"experiment-1","train_basis_points":8000}'
.venv/bin/python clients/cli/m1.py status JOB_UUID
```

用实际返回值替换 `JOB_UUID`。`8000` 产生 split 标签，不是只导出 80% 行。CLI 默认等待；`--no-wait` 时自行查状态。成功后按[HTTP 契约](../../api/http/m1-openapi.json)下载 parquet/对象。

对照固定源核对 manifest 的 view、ID/version/split 与导出行。seed 只有连同源、身份、规则和集合固定才有意义。当前无 SQL 选样/投影、标签 JOIN 或分组 split。

## 消费与释放

```sh
.venv/bin/python clients/cli/m1.py cancel JOB_UUID
# 仅在所有消费者结束后释放：
.venv/bin/python clients/cli/m1.py release JOB_UUID
```

release 删除终态结果并释放 pin，后续访问为 404；不是训练框架消费 checkpoint。若清文件后目录提交失败，应重试同 job 对账，不保证结果仍可下载。

上游过期、对象替换或授权失效时不能自动换 latest。best-effort 来源不能长期复现；须先获得覆盖完整依赖的托管副本或上游保护。

## 验收训练场景

| 检查 | 独立断言 |
| --- | --- |
| 样本 | 固定源独立计算选择结果，核对 ID/version、不丢不重 |
| 对齐 | 父版本/坐标准确，缺模态策略一致 |
| 划分 | 重跑一致、分组无泄漏，不能只查 seed |
| 并行 | worker 覆盖/互斥，排序、混洗与恢复明确 |
| 生命周期 | 新发布、撤权、取消、pin/GC 和重启不漂移/泄露 |
| 成本 | 样本/字节吞吐、请求、随机读取放大、缓存与总内存 |

当前证据主要覆盖全视图导出与 pin；覆盖率或文件可下载不能替代完整训练场景。
