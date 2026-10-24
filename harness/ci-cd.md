# 当前本机质量保障与 CI/CD 暂停

2026-10-24用户明确要求：暂时停用GitHub Actions CI/CD及PR CI卡点，当前使用本机自测保障代码合入质量；项目达到一定完整度后重新讨论。依据[ADR0023](../docs/decisions/0023-team-issues-and-local-quality.md)，优先于ADR0009/0019及旧计划的远端必需检查条款。

## 当前执行状态

| 项目 | 当前规则 |
| --- | --- |
| GitHub质量工作流 | `Quality harness`，ID 387490345，已通过仓库API设为 `disabled_manually` |
| GitHub诊断工作流 | `Frozen worker diagnosis`，ID 390094932，已通过仓库API设为 `disabled_manually` |
| PR远端CI准入 | 暂停，不等待 `quality (Python 3.11)` / `quality (Python 3.14)` 或main push绿灯 |
| 本机质量 | 适用模块自测、真实配对/系统检查、独审、正常hook和精确main证据仍必需 |
| CD/发布 | 没有由本次决定授权部署；完整release、安全/恢复/环境义务保留 |

机器可读决定见[ci-state.json](ci-state.json)。当前质量工作流[YAML](../.github/workflows/check.yml)保留供未来恢复；诊断工作流的历史登记路径为`.github/workflows/worker-reproducer.yml`，当前树无该文件，但远端登记的工作流同样已停用。配置文件存在/仍有事件声明不表示远端工作流已启用。实际状态以GitHub API为准，新增或重命名workflow也须保持停用。2026-10-24执行停用后已核两工作流状态、无活动run；这是当时快照，后续管理员变更必须重新核对。

本次已授权取消PR的远端CI准入，不修改无关审批/分支保护。若平台仍有实际required status check阻断，集成者先读有效规则，再仅解除已授权的CI context并记录前后状态；不能据此关闭独立审查、允许强推或扩大部署权限。没有平台规则证据时不能声称保护已配置或已解除。

## 本机合入质量闭环

1. 模块负责人按[开发流程](development-workflow.md)对实际变更自测：单元/静态、真实依赖功能与负例，以及适用的性能/预算/故障。用现有harness/script，不把mock通过升级为系统通过。
2. 专职系统测试独立负责真实跨模块配对和用户旅程，独立oracle、同view/版本/权限、总预算/取消/unknown/清理/恢复；性能与长稳在受控环境单独验收。
3. 集成者核源码、依赖、文件范围、复核和本地报告，正常hook提交；合入后核精确main、适用检查、报告/checkpoint和远端SHA。只因实际修改、失败或未解决风险补验证，不为管理格式无风险重跑全部历史。
4. 当前CI记为 `PAUSED_BY_USER / NOT_RUN`；既有失败保留，不能改成PASS。缺少本地命令/证据、timeout/failure/missing仍不能标绿。模块、配对、main和release分层记录，完整performance/stability/soak planned仍阻断release。

本机模块/组件预算、输入、strict100%和原覆盖排除不变。托管GitHub runner时间容量检查当前作为恢复CI前义务保留，不成为本机质量阶段新建分片/union工具的前置。本机实际命令仍执行原适用超时和完整输入，不能因远端暂停而缩减。

## 恢复CI/CD的条件

由用户重新讨论并明确授权后，先固定可发布范围、受控runner/环境、真实全部命令及容量、凭据/权限、日志与报告保留、必要的分段证据语义；再实际运行候选、核对应head/base和结果，才重新讨论PR required checks与平台强制。

恢复操作应更新ADR与机器决定、核远端workflow状态及有效保护规则；不能仅修改YAML或恢复开关便声称CI通过。CI/CD优化独立Issue管理，不自动混入数据库交付。历史Actions artifacts通常仅保留14天，必要证据继续在本地按原规则归档；本地归档不等于异地备份。

CD仍需明确不可变构建物、版本/摘要、部署目标、身份与授权、健康检查、迁移/备份、unknown对账及恢复/补偿。关闭CI或代码回退不撤销外部副作用，也不自动开启部署。
