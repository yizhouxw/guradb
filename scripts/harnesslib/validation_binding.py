"""Bind profile to selection/execution logic, before running or trusting evidence."""
import hashlib

from .policy import HarnessError
from .validation import validation_plan
from .validation_registry import digest
from .stages import resolve_stage

LOGIC_INPUTS = ("scripts/harness.py", "scripts/harnesslib/policy.py", "scripts/harnesslib/runner.py",
                "scripts/harnesslib/validation_registry.py", "scripts/harnesslib/validation.py",
                "scripts/harnesslib/validation_binding.py", "scripts/harnesslib/check_evidence.py",
                "scripts/harnesslib/stages.py", "scripts/harnesslib/core_rust.py",
                "scripts/harnesslib/workflow.py", "scripts/harnesslib/version_control.py", "scripts/harnesslib/task_state.py",
                "scripts/unit_coverage.py", "scripts/coverage_scope.py", "scripts/coverage_policy.py",
                ".githooks/pre-commit", ".github/workflows/check.yml")


def bound_plan(root, paths, policy, architecture, invariants, level="auto", modules=(), scope="change",
               stage="auto", core_flow=None):
    stage, core_flow = resolve_stage(root, stage, core_flow)
    value = validation_plan(root, paths, policy, architecture, invariants, level, modules, scope, stage, core_flow)
    logic = set(LOGIC_INPUTS) | {path.relative_to(root).as_posix()
                                 for path in (root/"scripts/harnesslib").rglob("*.py")}
    if any((root/name).is_symlink() for name in logic):
        raise HarnessError("selection/execution logic cannot be a symlink")
    value["profile"]["selection_execution_logic"] = {
        name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sorted(logic)}
    inputs = set()
    for suite in value["profile"]["suites"].values():
        for command in suite["commands"]:
            inputs.update(arg for arg in command if "{" not in arg and not arg.startswith("/")
                          and (root/arg).is_file())
    value["profile"]["command_inputs"] = {name: hashlib.sha256((root/name).read_bytes()).hexdigest()
                                            for name in sorted(inputs)}
    value["profile"]["suite_order"] = list(value["profile"]["suites"])
    value["profile"]["maximum_command_seconds"] = sum(
        suite["timeout_seconds"] * len(suite["commands"])
        for suite in value["profile"]["suites"].values() if suite["state"] == "ready")
    value["profile_sha256"] = digest(value["profile"])
    return value


def claim(report):
    """A receipt/checkpoint must retain level, not promote 'passed' to system."""
    if report["schema_version"] == 1:
        return {"report_schema": 1, "level": "legacy-" + report["scope"],
                "product_quality": report.get("product_quality", "legacy-selected-gates")}
    selected = report["validation"]
    profile = selected["profile"]
    return {"report_schema": 2, "level": profile["level"], "modules": profile["modules"],
            "stage": selected["stage"], "core_flow": selected["core_flow"],
            "pairs": profile["pairs"], "profile_sha256": selected["profile_sha256"],
            "selection_base": report["selection_base"], "batch": report.get("batch")}
