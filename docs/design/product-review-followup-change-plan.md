# 产品技术评审落实：变更与验收计划

日期：2026-10-20。状态：文档修订与内容复核完成；检查、提交和主线交付状态以任务归档及PR证据为准。仅修改产品技术文档与后续实施路径。

## 目标、范围与恢复点

用户要求根据本轮数据库与 AI 训练评审修改项目文档。可观察结果：读者能找到首个图文检索到训练样板、共同查询与按需读取门槛、训练样本/采样/复现边界、质量与生命周期验收，以及可提前运行的纵向集成路径。

task：`product-review-followup`；owner：本任务实现者，单独执行复核与集成；分支 `codex/product-review-followup`；原始 base `79e4d00e43e1f42bfd7907e1580ea152642eab37`，起点无用户改动。worktree：`/Users/yizhou/.codex/worktrees/product-review-followup/guradb`；起始 checkpoint：`checkpoints/20261020T051619Z-before-product-review-followup-8992f32a`。无依赖 PR，所有本轮文件由本任务独占。

允许范围：根 README、docs 导航/vision/architecture/roadmap、product 合同与功能架构、user 的 README/training/data-model/retrieval/ingestion、概要/模块/运行设计、训练专题、本计划、并行实施计划、ADR0020、ADR0018后续决定导航与决策索引、复核记录。禁止修改运行时代码、API schema、依赖锁、能力白名单和质量门禁。

本轮接受产品/设计与实施原则，不把推荐组件、未来 schema、框架适配或规模目标标成已实现；不缩小 M3/M4、长期多模态目标或既有验收义务。不做运行时迁移、部署、客户数据接入或模型训练。

## 风险与不变量

预判 `plan --path` 选择 repository/policy/contracts/harness-tests，runtime_changed=false；没有自动命中的运行时模块/INV。人工核对 INV 中的稳定身份、固定视图、索引完整性、源/发布双 fencing、未知提交、pin/GC/撤权及端到端预算。主要文档风险是：新旧依赖矛盾、把导出唯一性误用到采样、先降级保留再隐瞒承诺、用媒体大体积替代索引超缓存证据。

## 用户文档先行与场景映射

本轮先编辑以下用户目标合同；所有新操作标待实现，不发明可执行命令。无行为代码变更，所以文档检查只证明文档/契约一致性。

| 场景 / 手册 | 成功与拒绝合同 | 后续验证 / 本轮证据 |
| --- | --- | --- |
| 图文检索到训练 / user/README、retrieval | 同view证据与选样；固定语言/模型、授权和新鲜度；未支持语言/空间拒绝 | I1/I2 的真实后端与标注真值；本轮仅内容复核 |
| 样本与消费 / user/training、data-model | sample身份、角色/版本、分组隔离、数据/顺序复现分层；缺模态/续读能力拒绝 | I3 独立reader与真实框架；本轮不宣称运行通过 |
| 替换/下架 / user/ingestion | 完整受支持快照重建并发布；历史保留、撤权、擦除分别说明 | I2刷新/权限负例；不把源delete忽略为append |

前置：后续 P01 固定可分发样本/许可、语言/模型与真值，P00 冻结分批合同；权限/预算、保留和兼容按具体检查点预注册。当前 alpha 的全部命令/上限保持原样。行为实现前仍需补正式 API/命令和测试映射，不把本表代替详细设计。

## 实施顺序与验证

1. 修改用户目标合同，再更新产品/训练详细语义、范围读取与质量成本要求。
2. 更新概要、模块、路线图与工作包依赖；分批合同和 I1–I3 是既有 G1 内的早期集成，不新增竞争里程碑。
3. ADR0020 保存长期决定；逐项复核评审意见、导航、依赖可执行性和未实现边界。
4. 运行 `.venv/bin/python scripts/harness.py plan`、`check` 与 `git diff --check`；复核后提交，提交后对原始 base 重验、task-finish、推送和 PR CI；按既有流程合入并核验精确 merge。

功能/性能/故障不因文档修改重跑；原有完整 performance/stability/soak 保持 planned，缺少真实样本、框架消费、规模与生产报告的事实不改变。检查失败保留日志；恢复仅在新目录使用上述 checkpoint。没有数据副作用；文档撤销通过后续 PR，不重写历史。

## 结果

实际内容复核见[评审落实记录](../reviews/2026-10-20-product-review-followup.md)。最终命令、commit、完整范围报告、receipt/checkpoint 和 PR/主线证据由任务归档及 PR 交付记录绑定，不在提交前填成功。
