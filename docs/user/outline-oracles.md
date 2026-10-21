# 企业图文样板与独立真值

状态：P01 首片离线实现已通过局部测试，独立复核与首次完整门禁已通过，提交后代码绑定待归档；仅供开发/验收的 synthetic fixture，不是数据库可调用 API、业务相关性结论或产品性能 baseline。B/C 资产、片段和训练字段为 fixture 私有格式，公共合同仍由 P00 冻结。

## 场景合同

| 字段 | 合同 |
| --- | --- |
| 场景 ID / 目标 | P01-SYNTHETIC：从可分发中文图文语料，重现固定版本关系过滤、精确检索、受限图和训练样本组真值 |
| 先行记录 | 本页与 `docs/design/outline-oracles-change-plan.md` 在 fixture/oracle 行为代码前创建；task receipt `p01-outline-oracles` 保存原始基点 |
| 前置 | Python 3.11+；本仓库固定 fixture；无服务、网络、凭据、真实用户数据或真实模型权重 |
| 输入白名单 | `outline-synthetic-v1`；zh-CN 固定人工分词；3 维手工合成向量，固定模型空间；UTF-8 文本和小型 SVG 代码资产 |
| 输出白名单 | 固定 manifest SHA-256、原生 int8/NULL 关系真值、精确 squared-L2/BM25 排名、typed-edge 有界可达集合、显式 group/split 与一种 query/positive/negative/image 样本 |
| 拒绝 | 输入摘要或成员版本变化、重复身份、错误父版本/坐标/模型/维数、缺必要模态、跨 split 重复或成员、不支持谓词/图深度；真实 ANN、框架/训练恢复及公共 B/C API 不在首片 |
| 权限与预算 | 仅本地 fixture 读取；oracle 不替代授权检查。最大文件 1 MiB、合计 2 MiB、100 条记录、图深度 1–3；质量/成本合同见 fixture 的 budgets.json |
| 兼容/恢复 | 版本 v1 固定；数据变化需新 fixture 版本和新 manifest。无数据库/外部副作用，恢复使用 Git checkpoint；不迁移历史 alpha 数据 |
| 实测 | 离线 CLI 与 16 项局部契约测试通过；独立复核无阻断发现；首次完整 harness 五项门禁已通过（报告 `artifacts/harness/20261020T233913Z-f44987e8/report.json`）；提交后代码绑定由 task-finish 归档。局部日志在 `artifacts/outline-p01/` |

## 离线操作

在仓库根执行，输出到 stdout；如需保存日志请放 `artifacts/`：

```sh
.venv/bin/python -m tests.outline_oracles
.venv/bin/python -m unittest tests.contracts.test_outline_oracles -v
```

第一条验证固定输入及已声明的独立真值，输出 fixture digest、版本集合、过滤选择率、训练组/样本计数、事实/向量/索引/媒体字节数和明确的 missing 项。`feature_values_bytes` 仅按 oracle 的 float64 坐标计算逻辑值字节数；物理 JSON 大小另在 vectors 工作集统计。摘要不包含运行耗时/QPS；不存在真实缓存、对象 GET、RSS 或生产索引测量。

int8 原始真值保留完整有符号 64 位 JSON 整数；映射 CF1-A scalar 时使用规范十进制字符串，NULL 使用 `{type: "null", value: null}`。生产查询/排名/split 实现不被 oracle 导入；golden 由固定成员表与手工可核对公式复核。

每个训练样本使用同一文档族的 query/positive/negative 和 positive 图像，先固定文档族的 split，再引用片段和样本。重复内容与旧版本留在同组；缺模态记录保留在语料并按显式规则报告排除，不静默丢弃。

## 证据限制

语料、图像、向量和相关性关系全部人工构造，许可在 fixture 内明确授予 CC0-1.0。向量模型只是稳定的坐标空间名称，没有真实 encoder、tokenizer 权重或图文语义能力。算法精确真值可以验证结果与版本；人工业务相关性、真实 embedding/reranker 质量、框架消费、多 worker、撤权/pin/取消、真实索引/对象存储成本、冷热与超缓存均为 missing；后续环境仅使用本机模拟云，真实云与多机认证未验证。后续 I1/I2/I3、P14 分别补验。
