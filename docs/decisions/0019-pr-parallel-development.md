# ADR 0019：GitHub PR 与多分支并行开发

- 状态：已采用工程约定；仓库文档/模板落地，远端保护待另行授权与核验
- 日期：2026-10-20
- 依据：用户要求为本项目设定基于 GitHub Pull Request 的多分支并行开发流程
- 规范：[PR 并行流程](../../harness/parallel-development.md)、[版本追溯](../../harness/version-control.md)、[CI/CD](../../harness/ci-cd.md)

## 决定

所有开发（含文档）默认一任务一 `codex/<task>` 分支和独立 worktree，以 main 为持续集成主线，通过 GitHub PR 审查与 CI 后串行合入。该决定替代 [ADR 0008](0008-git-traceability-and-recovery.md) 中普通任务直接main、开发后本地合并推送的约定；保留其非破坏恢复、原始范围门禁、commit绑定证据和checkpoint。

协调者冻结公共合同、owner/文件域和依赖，热点文件单一owner，依赖未完成的PR保持Draft/blocked。模块fake证据与真实集成分开，不能通过分支隔离假定语义无冲突。实现者维护分支任务证据，审查者单独复核，集成者串行验证每次合入。

采用 GitHub merge commit，保留原始分支提交与receipt对应关系。同步主线正常merge，不强推、不重写共享历史；不用squash/rebase merge和本地直接push main。每次同步/修复重验原始任务范围，PR检查必须匹配当前候选；合入后对合并前主线到最终merge SHA验证，主线push CI与分支证据分别记录。

用户既有开发推送授权按本流程落实为推送任务分支、创建PR及满足门禁后PR合入，不逐次询问；远端设置、权限/保护、发布和部署仍另行授权。单人模式采用单独复核记录，不伪造作者Approval；需要他人复核而无人可审时阻断。后续有合格第二审查者及授权时才启用强制审批。

## 取舍与限制

直接main操作少，但难以隔离并行任务和保留合入审查入口；长期develop分支和任意堆叠PR增加基点、集成和证据管理成本，因此默认短任务分支直接面向main。merge commit保留追溯但历史不完全线性；禁止与linear-history保护同时配置。

现有worktree隔离源码和task状态，不隔离共享Git对象库或外部数据库、Docker和性能资源，任务必须另外分配资源。远端required checks与保护才提供平台强制；文档、hook和人工串行操作不能保证阻止外部并发写入。私有仓库能力受GitHub方案限制，本轮不声称保护已启用。

## 验证与恢复

本轮为工程文档/PR模板修订，无数据库用户行为、数据迁移或性能影响。验证仓库链接/政策、契约与harness自测，单独复核旧main规则是否被替代、负例/单人审批/竞争/证据时效是否明确；提交后精确绑定commit报告，推送分支后实际建立PR并核对远端检查。远端保护验收在授权配置后独立记录。

已有dirty main任务保留原现场，迁移到新分支时显式核对diff与任务承接；不自动stash/stage/清理。主线错误通过修复/revert PR保留历史，数据副作用单独对账补偿。流程本身可由后续ADR修订，不重写历史决定。
