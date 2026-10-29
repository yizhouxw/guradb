"""A task has a durable base, bounded review record and verified completion."""

from datetime import datetime, timezone
from pathlib import Path
import re
from uuid import uuid4

from .check_evidence import validate_report
from .policy import HarnessError, git
from .task_state import active_base, read_task, task_lock, write_task
from .version_control import checkpoint, status
from .validation_binding import claim
from .stages import resolve_stage, stage_options


def start_task(root: Path, label: str, objective: str, configuration: tuple,
               stage="hardening", core_flow=None) -> dict:
    stage_options(stage, core_flow)
    if stage == "auto":
        raise HarnessError("task-start requires an explicit stage")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", label):
        raise HarnessError("task label must be 1..48 lowercase letters, digits or hyphens")
    if not objective.strip():
        raise HarnessError("task objective cannot be empty")
    with task_lock(root):
        previous = read_task(root)
        if previous and previous["status"] == "active":
            raise HarnessError("task already active; resume or explicitly abandon it before starting another")
        current = status(root)
        if not current["clean"] or not current["head"] or not current["branch"]:
            raise HarnessError("task-start requires a clean committed branch; isolate existing changes first")
        point = checkpoint(root, "before-" + label, configuration[0])
        value = {"schema_version": 1, "id": uuid4().hex, "label": label, "objective": objective,
                 "status": "active", "worktree": str(root.resolve()), "branch": current["branch"],
                 "base_commit": current["head"], "checkpoint": point["checkpoint"],
                 "stage": stage, "core_flow": core_flow,
                 "started_at": datetime.now(timezone.utc).isoformat()}
        write_task(root, value)
        return value


def finish_task(root: Path, report_path: Path, review: str, configuration: tuple) -> dict:
    if not review.strip():
        raise HarnessError("completion requires a review summary and unresolved limitations")
    with task_lock(root):
        base = active_base(root)
        if base is None:
            raise HarnessError("no active task to finish")
        report = validate_report(root, report_path, configuration)
        if report["scope"] == "bootstrap" or report["selection_base"] != base:
            raise HarnessError("task completion needs change/release evidence covering its original base")
        if report["schema_version"] == 2:
            selected = report["validation"]
            if (selected["stage"], selected["core_flow"]) != resolve_stage(root):
                raise HarnessError("task completion stage must match the active receipt")
        value = read_task(root)
        point = checkpoint(root, value["label"] + "-done", configuration[0], report_path, configuration)
        value["validation"] = claim(report)
        value.update(status="completed", final_commit=point["commit"], review=review,
                     final_checkpoint=point["checkpoint"], evidence_directory=point["evidence_directory"],
                     finished_at=datetime.now(timezone.utc).isoformat())
        write_task(root, value)
        return value


def abandon_task(root: Path, reason: str) -> dict:
    if not reason.strip():
        raise HarnessError("abandonment needs a reason and recovery/handoff note")
    with task_lock(root):
        value = read_task(root)
        if not value or value["status"] != "active":
            raise HarnessError("no active task to abandon")
        value.update(status="abandoned", reason=reason,
                     final_commit=git(root, "rev-parse", "HEAD").decode().strip(),
                     finished_at=datetime.now(timezone.utc).isoformat())
        write_task(root, value)
        return value
