# 本地任务入口与归档

唯一活跃根：`/Users/chad/dev/guradb/artifacts/team-state`，host=`local/xiaoweideMac-Studio.local`；所有worktree使用同一显式绝对根，禁止各自artifacts产生第二份当前状态。该根已被现有忽略规则排除Git，跨机未同步/证据不可取=unavailable/HOLD，不是远端备份。活跃任务索引为根内 `tasks/README.md`，当前状态为 `tasks/<task-id>/TASK.md`。

本目录只放版本化模板/稳定点归档/本次治理变更计划。日常派发、任务状态、交接、记忆发现无需每条提交/PM源码任务或整轮check，由具名单写者本地保存并核版本/来源；稳定点批量归档必要摘要。归档不反向覆盖活跃任务。普通代码/规范/长期记忆变更仍须正常门禁与PR；忽略目录不是产品实现通道。

按[模板](../templates/local-task.md)建独立task ID，先查重。本地TASK是协作状态权威，Git-admin receipt是原始B/生命周期证据；必须分别核TASK与 `task-status`，不手工结束receipt。Issue仅可选ref。每次更新标revision、观察时刻、写者实例/稳定身份、证据可取性和下一动作；过期/未知不推PASS或授权。

本次版本化[治理TASK](20261026-offline-governance/TASK.md)记录变更计划与归档证据，不承担后续日常当前状态；本次活跃副本同ID，见共享根任务索引。最终归档由E显式合并回此任务，不自动同步两边。
