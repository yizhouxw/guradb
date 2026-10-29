"""ADR0027 bounded fixed-read profile; no module/system/release certification."""
from pathlib import PurePosixPath
import hashlib

from .policy import HarnessError
from .task_state import active_base, read_task, task_lock, write_task

STAGES = ("auto", "core", "hardening")
CORE_FLOW = "fixed-read"
CORE_PATHS = {
    "crates/guradb-common/src/protocol.rs",
    "crates/guradb-query/src/lib.rs", "crates/guradb-query/src/sql.rs",
    "crates/guradb-query/src/fixed.rs", "crates/guradb-query/tests/unit/fixed.rs",
    "crates/guradb-gateway/src/main.rs", "crates/guradb-gateway/src/routes.rs",
    "crates/guradb-gateway/src/state.rs", "crates/guradb-storage/src/lib.rs",
    "api/http/openapi.json", "api/capabilities/v1.json", "scripts/fixed_read_core_acceptance.py",
    "scripts/harness.py", "harness/policy.toml", "harness/validation.toml",
}
CORE_PACKAGES = ("guradb-common", "guradb-storage", "guradb-query", "guradb-gateway")
SELFTESTS = ("test_policy.py", "test_architecture.py", "test_runner.py", "test_workflow.py",
             "test_version_control.py", "test_evidence.py", "test_process_cleanup.py",
             "test_validation*.py", "test_core_stage.py")


def stage_options(stage, core_flow):
    if stage not in STAGES or (stage == "core" and core_flow != CORE_FLOW):
        raise HarnessError("core stage requires registered --core-flow fixed-read")
    if stage != "core" and core_flow is not None:
        raise HarnessError("--core-flow requires --stage core")
    return stage, core_flow


def resolve_stage(root, stage="auto", core_flow=None):
    stage_options(stage, core_flow)
    if stage != "auto":
        return stage, core_flow
    task = read_task(root)
    if task and task["status"] == "active":
        active_base(root)  # The original task branch/base must remain valid.
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


def core_suites(root, paths, policy):
    unknown = [path for path in paths if not (documentation_path(path) or path in CORE_PATHS
               or path.startswith(("scripts/harnesslib/", "tests/harness/")) and path.endswith(".py"))]
    if unknown:
        raise HarnessError("core fixed-read profile has unmapped changes: " + ", ".join(unknown))
    suites = {name: policy["suites"][name] for name in ("repository", "policy", "contracts")}
    tests = sorted(set(SELFTESTS) | {PurePosixPath(path).name for path in paths
                                  if path.startswith("tests/harness/") and path.endswith(".py")})
    test_inputs = {}
    for pattern in tests:
        matched = list((root/"tests/harness").glob(pattern))
        if not matched:
            raise HarnessError("core harness selftest input missing: " + pattern)
        for path in matched:
            if path.is_symlink() or not path.is_file():
                raise HarnessError("core harness selftest must be a regular file")
            test_inputs[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    suites["core-harness"] = {"state": "ready", "timeout_seconds": 120,
        "test_inputs": test_inputs,
        "commands": [["{python}", "-m", "unittest", "discover", "-s", "tests/harness", "-p", pattern]
                     for pattern in tests]}
    rust = sorted(path for path in paths if path.endswith(".rs") and (root/path).is_file())
    package_args = [item for name in CORE_PACKAGES for item in ("--package", name)]
    commands = ([["{python}", "scripts/harnesslib/core_rust.py", *rust]] if rust else [])
    commands += [["{python}", "scripts/cargo.py", "clippy", *package_args,
                  "--all-targets", "--locked", "--", "-D", "warnings"],
                 ["{python}", "scripts/cargo.py", "test", *package_args, "--locked"]]
    suites["core-rust"] = {"state": "ready", "timeout_seconds": policy["suites"]["rust"]["timeout_seconds"],
                           "commands": commands}
    suites["core-fixed-read"] = {"state": "ready", "timeout_seconds": 300,
        "commands": [["{python}", "scripts/fixed_read_core_acceptance.py", "--run-dir", "{run_dir}/fixed-read-core"]]}
    return suites
