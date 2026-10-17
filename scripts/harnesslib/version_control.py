"""Git checkpoints and non-destructive recovery; never reset the caller's tree."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from .policy import HarnessError, git, load
from .runner import checkout_digest
from .check_evidence import archive_report, validate_report


def status(root: Path) -> dict:
    head = git(root, "rev-parse", "--verify", "HEAD", allow_failure=True).decode().strip()
    branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD", allow_failure=True).decode().strip()
    dirty = git(root, "status", "--porcelain=v1", "--untracked-files=all")
    refs = git(root, "for-each-ref", "--format=%(refname:short)", "refs/tags/checkpoints/")
    return {"head": head or None, "branch": branch or None, "clean": not dirty,
            "checkpoints": refs.decode().splitlines(),
            "remote_names": git(root, "remote").decode().splitlines()}


def require_committable_tree(root: Path) -> None:
    # Tests must inspect the exact snapshot that will be committed. Do not stage
    # somebody else's changes automatically to satisfy this requirement.
    if git(root, "diff", "--name-only", "--") or git(
            root, "ls-files", "--others", "--exclude-standard", "-z"):
        raise HarnessError("unstaged/untracked files: stage only intended changes or use an isolated worktree")
    git(root, "diff", "--cached", "--check")


def install_hooks(root: Path) -> dict:
    previous = git(root, "config", "--get", "core.hooksPath", allow_failure=True).decode().strip()
    if previous not in {"", ".githooks"}:
        raise HarnessError("existing core.hooksPath preserved; integrate hooks manually")
    hook = root / ".githooks" / "pre-commit"
    if not hook.is_file():
        raise HarnessError("missing repository pre-commit hook")
    if os.name == "posix" and not os.access(hook, os.X_OK):
        raise HarnessError("repository pre-commit hook is not executable; restore its Git executable mode")
    git(root, "config", "--local", "core.hooksPath", ".githooks")
    return {"hooks_path": ".githooks", "scope": "local repository config"}


def checkpoint(root: Path, label: str, policy: dict, report_path: Path | None = None,
               configuration: tuple | None = None) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", label):
        raise HarnessError("checkpoint label must be 1..64 lowercase letters, digits or hyphens")
    current = status(root)
    if not current["head"] or not current["clean"]:
        raise HarnessError("checkpoint requires an existing commit and clean tree; never auto-commit unknown changes")
    metadata = {"schema_version": 1, "kind": "git-checkpoint", "commit": current["head"],
                "checkout_digest": checkout_digest(root, policy), "quality": "not_assessed"}
    if report_path is not None:
        report = validate_report(root, report_path, configuration or load(root))
        metadata.update(quality="selected_gates_passed", scope=report["scope"],
                        selection_base=report["selection_base"],
                        report_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest(),
                        evidence_directory=archive_report(root, report_path, report))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    reference = f"checkpoints/{stamp}-{label}-{uuid4().hex[:8]}"
    git(root, "tag", "-a", reference, "-m", json.dumps(metadata, ensure_ascii=False), current["head"])
    return {"checkpoint": reference, **metadata}


def recover(root: Path, reference: str, destination: Path) -> dict:
    if not reference.startswith("checkpoints/"):
        raise HarnessError("recovery requires an explicit checkpoints/... tag")
    git(root, "check-ref-format", "refs/tags/" + reference)
    commit = git(root, "rev-parse", "--verify", "--end-of-options",
                 "refs/tags/" + reference + "^{commit}").decode().strip()
    destination = destination.expanduser().resolve()
    if destination.exists() or destination.is_relative_to(root.resolve()):
        raise HarnessError("recovery destination must be a new path outside the current checkout")
    # Git hooks export e.g. GIT_INDEX_FILE=.git/index. A new worktree has a
    # .git *file*, so those caller-local paths cannot be carried into checkout.
    environment = os.environ.copy()
    for name in git(root, "rev-parse", "--local-env-vars").decode().splitlines():
        environment.pop(name, None)
    git(root, "worktree", "add", "--detach", "--", str(destination), commit, environment=environment)
    return {"checkpoint": reference, "commit": commit, "recovery_directory": str(destination),
            "original_tree": "preserved", "mode": "detached worktree"}
