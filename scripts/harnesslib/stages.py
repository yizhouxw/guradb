"""ADR0028 single-process alpha scope and verified retirement; no release claim."""
import hashlib
import json
from pathlib import PurePosixPath

from .policy import HarnessError, normalize_path
from .task_state import active_base, read_task, task_lock, write_task

STAGES = ("auto", "core", "hardening")
CORE_FLOW = "simple-alpha"
ACTIVE_FILES = {
    "scripts/sample_torch_client.py",
    "scripts/prepare_clip_features.py", "requirements-clip-macos-arm64.lock", "docs/user/clip-queries.json",
    "Cargo.toml", "Cargo.lock", "crates/guradb/Cargo.toml", "Makefile", "requirements-dev.lock", "requirements-dev.txt",
    "scripts/prepare_text_corpus.py", "scripts/alpha_acceptance.py", "scripts/prepare_coco_metadata.py", "scripts/prepare_coco_caption.py", "scripts/cargo.py", "scripts/check_repository.py", "scripts/harness.py",
    "harness/policy.toml", "harness/architecture.toml", "harness/validation.toml", "harness/invariants.toml",
    "harness/alpha-retired.json", "api/capabilities/v1.json",
}


def stage_options(stage, core_flow):
    if stage not in STAGES or (stage == "core" and core_flow != CORE_FLOW):
        raise HarnessError("core stage requires registered --core-flow simple-alpha")
    if stage != "core" and core_flow is not None:
        raise HarnessError("--core-flow requires --stage core")
    return stage, core_flow


def resolve_stage(root, stage="auto", core_flow=None):
    stage_options(stage, core_flow)
    if stage != "auto":
        return stage, core_flow
    task = read_task(root)
    if task and task["status"] == "active":
        active_base(root)
        return stage_options(task.get("stage", "hardening"), task.get("core_flow"))
    return "hardening", None


def set_task_stage(root, stage, core_flow=None):
    stage_options(stage, core_flow)
    if stage == "auto":
        raise HarnessError("task-stage requires an explicit stage")
    with task_lock(root):
        if active_base(root) is None:
            raise HarnessError("task-stage requires an active task")
        task = read_task(root)
        task.update(stage=stage, core_flow=core_flow)
        write_task(root, task)
    return task


def documentation_path(path):
    return PurePosixPath(path).suffix in {".md", ".rst"}


def retirement(root):
    manifest = root/"harness/alpha-retired.json"
    value = json.loads(manifest.read_text())
    if set(value) != {"schema_version", "base_commit", "unsupported", "files"} or value["schema_version"] != 1:
        raise HarnessError("invalid alpha retirement manifest")
    retired = {}
    for entry in value["files"]:
        if (set(entry) != {"path", "reason", "category"} or not entry["category"].strip()
                or normalize_path(entry["path"]) != entry["path"]
                or not entry["reason"].strip() or entry["path"] in retired):
            raise HarnessError("invalid/duplicate alpha retirement path")
        if (root/entry["path"]).exists() or (root/entry["path"]).is_symlink():
            raise HarnessError("retired path still present: " + entry["path"])
        retired[entry["path"]] = entry["reason"]
    return retired


def core_suites(root, paths, policy):
    retired = retirement(root)
    unknown = [path for path in paths if not (documentation_path(path) or path in ACTIVE_FILES or path in retired
        or path.startswith(("crates/guradb/", "scripts/harnesslib/", "tests/harness/")) and path.endswith((".rs", ".py")))]
    if unknown:
        raise HarnessError("simple-alpha profile has unmapped changes: " + ", ".join(unknown))
    if any((root/"modules").rglob("*.py")) or any((root/"clients").rglob("*.py")):
        raise HarnessError("alpha cannot retain Python online demo modules")
    extras = [p.name for p in (root/"crates").iterdir() if p.is_dir() and p.name != "guradb"
              and any(p.rglob("*.rs"))]
    if extras:
        raise HarnessError("alpha production crates outside current scope: " + ", ".join(extras))
    suites = {name: dict(policy["suites"][name]) for name in
              ("repository", "policy", "harness-tests", "python", "rust", "functional")}
    test_inputs = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (root/"tests/harness").glob("test_*.py") if p.is_file() and not p.is_symlink()}
    if "tests/harness/test_alpha_stage.py" not in test_inputs:
        raise HarnessError("alpha stage evidence tests missing")
    suites["harness-tests"]["test_inputs"] = test_inputs
    suites["repository"]["retirement_manifest_sha256"] = hashlib.sha256((root/"harness/alpha-retired.json").read_bytes()).hexdigest()
    return suites
