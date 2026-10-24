# PM交接状态JSON模板

这是可复制的数据示例，不是Schema或可执行调度配置。填写规则、字段语义和七场景演练见[PM协调规则](../pm-coordination.md)。初始值未配置、未授权；复制代码块为动态JSON记录时先填实际值并完成规定核验，再将可定位的当前记录链接保存在项目PM协调Issue。勿将实时状态回写本模板。

```json
{
  "schema_version": 1,
  "record_kind": "pm-handoff-state",
  "template_only": true,
  "record_revision": 0,
  "project": {
    "repository_url": null,
    "coordination_issue_url": null,
    "current_record_url": null
  },
  "pm": {
    "role": "pm",
    "dri_session_id": null,
    "execution_owner_session_id": null,
    "machine_id": null,
    "authorization_ref": null,
    "owner_generation": 0,
    "authority_state": "unassigned"
  },
  "state": "uninitialized",
  "checked_at": null,
  "timezone": "Asia/Shanghai",
  "waiting_on": [
    {
      "task_issue_url": null,
      "role": null,
      "dri_session_id": null,
      "input_version": null,
      "input_evidence_ref": null,
      "ready_eta": null,
      "eta_basis": "unknown",
      "latest_commitment_at": null
    }
  ],
  "next_action": {
    "owner_session_id": null,
    "description": null,
    "trigger": null
  },
  "next_check_at": null,
  "next_check_basis": null,
  "latest_commitment_at": null,
  "unknown_backoff_step": 0,
  "schedule": {
    "id": null,
    "state": "not_configured",
    "machine_id": null,
    "target_session_id": null,
    "generation": 0,
    "readback_evidence_ref": null,
    "last_handled_event_ref": null,
    "last_handled_input_version": null,
    "last_handled_action_ref": null,
    "capability_evidence_ref": null,
    "exact_one_shot": "unverified",
    "pending_change": {
      "desired_next_check_at": null,
      "desired_generation": null,
      "intent_evidence_ref": null
    }
  },
  "handoff": {
    "state": "not_requested",
    "from_session_id": null,
    "from_machine_id": null,
    "to_session_id": null,
    "to_machine_id": null,
    "authorization_ref": null,
    "old_schedule_stop_state": "unconfirmed",
    "old_schedule_stop_evidence_ref": null,
    "new_owner_acceptance_ref": null
  },
  "blocked": {
    "since": null,
    "reason": null,
    "resolution_owner_session_id": null,
    "next_action": null,
    "fallback_owner_session_id": null,
    "fallback_action": null
  },
  "evidence": [
    {
      "issue_or_pr_url": null,
      "commit_sha": null,
      "repository_relative_ref": null,
      "sha256": null,
      "source_machine_id": null,
      "accessibility": "unknown",
      "accessible_copy_ref": null
    }
  ],
  "local_resources": [
    {
      "machine_id": null,
      "description": null,
      "local_path": null,
      "accessibility": "unknown",
      "recovery_ref": null
    }
  ]
}
```

`null`表示未填或未知，不是成功/无成本；`template_only`填写后改为false不构成授权。所有`*_ref`必须指向可定位且允许访问的证据；本地路径须填机器归属与可取性。只有顶层`next_check_at`为当前有效检查点；`pending_change`是未生效更新意图，平台回读确认前不得冒充有效代际。
