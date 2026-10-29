"""Worktree-local task receipts, independent of runtime policy validity."""

from contextlib import contextmanager
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from .policy import HarnessError, git


def state_path(root: Path, name: str = "task.json") -> Path:
    value = git(root, "rev-parse", "--git-path", "guradb/" + name).decode().strip()
    return (root / value).resolve()


def read_task(root: Path) -> dict | None:
    path = state_path(root)
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
            or value.get("schema_version") != 1 or value.get("status") not in {"active", "completed", "abandoned"}
            or not all(isinstance(value.get(key), str) and value[key] for key in
                       ("id", "label", "objective", "base_commit", "branch", "worktree"))
            or value["worktree"] != str(root.resolve())):
        raise HarnessError("invalid worktree task receipt; preserve it and inspect before continuing")
    if (not re.fullmatch(r"[0-9a-f]{32}", value["id"])
            or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value["base_commit"])):
        raise HarnessError("invalid task ID/base commit")
    stage, flow = value.get("stage", "hardening"), value.get("core_flow")
    if stage not in {"core", "hardening"} or (flow != "fixed-read" if stage == "core" else flow is not None):
        raise HarnessError("invalid task validation stage/core flow")
    return value


def write_task(root: Path, value: dict) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    history = state_path(root, "tasks/" + value["id"] + ".json")
    history.parent.mkdir(parents=True, exist_ok=True)
    # Archive first: a crash must not leave a completed current receipt whose
    # history is still active and later gets hidden by the next task.
    for destination in (history, path):
        temporary = destination.with_name("task-" + uuid4().hex + ".tmp")
        temporary.write_text(raw)
        temporary.replace(destination)


@contextmanager
def task_lock(root: Path):
    path = state_path(root, "task.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise HarnessError("task operation already locked; inspect owner/process before removing a stale lock") from error
    try:
        os.write(descriptor, str(os.getpid()).encode())
        yield
    finally:
        os.close(descriptor)
        path.unlink()


def active_base(root: Path) -> str | None:
    value = read_task(root)
    if not value or value["status"] != "active":
        return None
    branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD", allow_failure=True).decode().strip()
    base = value["base_commit"]
    if branch != value["branch"] or git(root, "merge-base", base, "HEAD").decode().strip() != base:
        raise HarnessError("active task branch/base changed; inspect receipt instead of silently rebasing quality scope")
    return base
