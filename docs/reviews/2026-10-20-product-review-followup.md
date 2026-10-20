# 产品技术评审落实与内容复核

日期：2026-10-20。任务：`product-review-followup`，原始base `79e4d00e43e1f42bfd7907e1580ea152642eab37`；[变更计划](../design/product-review-followup-change-plan.md)。本轮仅修改文档，无运行时、依赖、API schema、能力白名单或门禁变化。

## 评审意见与落实

| 意见 | 落实位置 | 可交付检查 / 未实现边界 |
| --- | --- | --- |
| 产品价值需聚焦并验证 | [产品合同](../product/product-contract.md)首个样板与对照；vision/概要/F10同步 | 企业图文→检索证据→embedding/reranker训练评估；冻结语言/模型/许可/质量及现有组合对照，未声称客户价值已测 |
| 共同查询优先于语言重写 | [架构](../architecture.md)、[模块合同](../design/outline-module-contracts.md)、I1 | 共同身份/view/授权/谓词/预算，各操作有独立真值；Python/Rust按责任保留 |
| 全量读取阻碍规模 | [运行设计](../design/outline-runtime-and-operations.md)§2.2.1、P03/P10/G2 | 按需provider、准确下推、批回表、流式背压；范围验证模式与相关工作集缓存分别证明 |
| 训练需样本与消费合同 | [训练合同](../product/training-contract.md)、[用户训练](../user/training.md)、P09/I3 | Sample/成员版本/recipe、持久group/split、D/O/M边界、策略化采样/尾批及真实框架；未提供新API/训练调度 |
| 算法正确性与业务相关性分开 | 运行设计§2.2.2、[检索指南](../user/retrieval.md)、P01/P14 | 精确算法、独立人工相关性、系统成本分别评估；RRF不作概率，未虚构业务指标结果 |
| 生命周期/新鲜度进入早期验收 | [数据合同](../product/data-contracts.md)、[接入指南](../user/ingestion.md)、I2/P07/P11 | 覆盖水位、续期失效对账、完整snapshot重新登记；源writer仍append，不放开DML/delete兼容 |
| 缩短首次集成等待 | [实施计划](../plans/2026-10-20-parallel-delivery.md)§2/5、[路线图](../roadmap.md)§1.2、[ADR0020](../decisions/0020-product-review-and-vertical-delivery.md) | CF1-A/B/C与I1/I2/I3逐片交付；保留P00–P20归属及G1–G5/M0–M4完整门槛 |

## 单独内容复核

实现后单独读取全部diff、工作包依赖与跨文档表述；本记录是单人分轮复核，不冒充第二位审查者或GitHub Approval。按现有PR流程集成。

复核并修正：

1. 同语义不能要求SQL扫描与ANN排名返回同一列表：I1明确共同上下文/谓词与各操作独立真值，检索及样本成员按身份/版本回查。
2. G1内提前集成不能抹掉原范围：G1仍要求P02–P12完整预览、受限Graph/关系、SQL准备、安装/恢复/兼容和薄客户端，G2–G5保持后续门槛。
3. 将snapshot替换误读为源覆盖写会扩大append边界：最小路径明确为权威源完整冻结版本重新登记/构建/发布；托管原位覆盖另立合同，不绕过源delete/schema白名单。
4. 媒体总字节不能证明ANN超缓存：修改R2说明，分别记录事实/向量/索引/媒体实际访问工作集与缓存；候选768维不改变当前256维限制。
5. 不把导出唯一性套用到所有训练迭代：训练合同、用户文档、F10、模块端口与P09区分采样/补齐/尾批；精确续读尚未实现须拒绝。
6. CF1不再要求一次冻结所有字段，但I1已有身份、授权、pin、预算/取消、登记幂等与发布fencing；后续子片先冻结其副作用/恢复合同，未冻结生产行为不得启用。
7. 架构迁移顺序与I1–I3对齐；首批样板所需语言/分析器随M2认证，不能把必要语言全部放到远期。当前ASCII能力白名单不变。

旧ADR0018加后续决定导航，历史复审不改写成新版本证据。用户文档先行修改，无行为代码。源对象权威、稳定ID、固定view、双fencing、未知提交、pin/GC/撤权和预算义务均保留。

## 验证与证据边界

预判及实际`harness.py plan`均选择repository/policy/contracts/harness-tests，runtime_changed=false；`git diff --check`已运行。实际check日志和提交后精确commit/checkout报告由本任务receipt/checkpoint与PR记录绑定，最终通过状态以这些报告为准，不以本页替代。

首次check（`artifacts/harness/20261020T052524Z-bd78fe67/report.json`）的contracts/harness-tests失败：新worktree仅装dev锁，缺少M0/M1锁中的pyarrow/tantivy等依赖，连带worker测试失败。保留原始报告与日志，按harness入口补齐三份原锁后重验；不修改依赖版本、测试或门禁来消除失败。

本轮未重跑数据库功能/性能/故障或训练框架，也未安装/部署竞品。官方PyTorch/Hugging Face/DataFusion资料只支持设计边界，实施仍需锁定兼容版本。完整performance/stability/soak保持planned；业务样本、相关性预算、范围后端认证、真实消费及多机/生产均待后续实现与证据。

没有数据迁移/外部数据副作用；文档可经修订PR恢复。分支提交/远端PR检查与精确主线merge报告分别核验，旧运行时或bootstrap通过不作本轮数据库质量声明。
