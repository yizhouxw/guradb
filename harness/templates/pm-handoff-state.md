# PM当前状态模板

在共享根 `pm/CURRENT.md` 维护一份，非可执行Schema/调度配置。职责见[团队规范](../team-collaboration.md)，恢复/调度见[PM协调](../pm-coordination.md)。

## 执行权与项目状态

- record_revision / checked_at / timezone：
- 唯一PM member_id、完整会话、机器、owner_generation、授权来源：
- project_state：ACTIVE / PAUSED_BY_USER / BLOCKED / HANDOFF_BLOCKED
- 当前产品目标与成功标准；治理等有限例外任务及授权：

## 当前目标索引（只链接TASK，不复制包内状态）

| 目标TASK | DRI | 结论/关键阻塞 | 下一决定/责任人/交付点 |
| --- | --- | --- | --- |
| 待填 | 待填 | 待填 | 待填 |

## 等待与唯一调度

- next_action / waiting_on及输入版本或结果引用：
- ready_eta或unknown、依据、最晚承诺；唯一next_check_at或null及原因：
- schedule ID / 状态 / 目标会话与机器 / generation / 实际回读证据：
- 仅更新期间填pending意图，保留旧有效值直到回读；重复输入/动作的去重引用：
- architecture_review：scheduled_for / last_review / next_due；暂停时不派发：
- 阻塞/失联：since、具体原因、解除owner/动作、真实兜底：

## 暂停、接管与历史

- 暂停来源、已停止/尚未确认对象、恢复条件；未知资源不得写成已清：
- 跨机时填旧owner/新owner、旧调度停止证据、新owner签收；unknown保持只读：
- 证据原件的机器/可取性、旧状态归档链接（不内嵌历史流水）：

只在状态变化时更新。空字段/模板/旧快照不是授权；本地路径不是备份，人工代际不是全局锁，分钟回退不是精确one-shot。用户决定和既有质量边界优先于模板。
