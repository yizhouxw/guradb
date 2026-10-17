"""Policy loading, change classification and a deterministic quality plan."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import subprocess
import tomllib


class HarnessError(ValueError):
    """A missing prerequisite or invalid quality input; never silently skip it."""


def read_toml(path: Path) -> dict:
    with path.open("rb") as stream:
        value = tomllib.load(stream)
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise HarnessError(f"{path}: unsupported schema_version")
    return value


def files(root: Path, ignored: set[str]) -> list[Path]:
    import os
    result = []
    for directory, subdirectories, names in os.walk(root):
        kept = []
        for name in subdirectories:
            if name in ignored or (Path(directory) == root and name + "/" in ignored):
                continue
            if (Path(directory) / name).is_symlink():
                raise HarnessError(f"checked source directory cannot be a symlink: {directory}/{name}")
            kept.append(name)
        subdirectories[:] = kept
        result.extend(Path(directory) / name for name in names)
    return sorted(result)


def normalize_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise HarnessError(f"expected repository-relative path: {value!r}")
    return path.as_posix()


def production_source(path: str, policy: dict) -> bool:
    return (PurePosixPath(path).suffix in policy["source_extensions"]
            and not any(path.startswith(prefix) for prefix in policy["non_runtime_prefixes"]))


def owner(path: str, architecture: dict) -> str | None:
    owners = [name for name, module in architecture["modules"].items()
              if any(path.startswith(prefix) for prefix in module["paths"])]
    if len(owners) > 1:
        raise HarnessError(f"ambiguous module ownership: {path}: {owners}")
    return owners[0] if owners else None


def validate_policy(policy: dict, architecture: dict, invariants: dict,
                    workloads: dict, faults: dict) -> None:
    suites = policy["suites"]
    for key in ("bootstrap_suites", "release_suites"):
        if not policy[key] or set(policy[key]) - set(suites):
            raise HarnessError(f"invalid suites in {key}")
    for name, suite in suites.items():
        if suite.get("state") not in {"ready", "planned"}:
            raise HarnessError(f"{name}: invalid suite state")
        timeout = suite.get("timeout_seconds")
        if type(timeout) is not int or not 1 <= timeout <= 3600:
            raise HarnessError(f"{name}: timeout must be 1..3600 seconds")
        commands = suite.get("commands")
        if not isinstance(commands, list):
            raise HarnessError(f"{name}: commands must be argv arrays")
        if suite["state"] == "ready" and not commands:
            raise HarnessError(f"{name}: ready suite has no command")
        if suite["state"] == "planned" and (commands or not suite.get("reason")):
            raise HarnessError(f"{name}: planned suite needs reason and no commands")
        for command in commands:
            if not isinstance(command, list) or not command or not all(
                    isinstance(arg, str) and arg for arg in command):
                raise HarnessError(f"{name}: invalid command argv")
    modules = architecture["modules"]
    for name, module in modules.items():
        if set(module["allowed"]) - set(modules) or name in module["allowed"]:
            raise HarnessError(f"{name}: invalid allowed module edge")
        for prefix in module["paths"]:
            if not prefix.endswith("/") or normalize_path(prefix) + "/" != prefix:
                raise HarnessError(f"{name}: invalid ownership prefix {prefix!r}")
    ids = [item["id"] for item in invariants["invariants"]]
    if len(ids) != len(set(ids)):
        raise HarnessError("duplicate invariant IDs")
    for item in invariants["invariants"]:
        if item["suite"] not in suites or set(item["modules"]) - set(modules):
            raise HarnessError(f"{item['id']}: invalid suite/module")
    workload_ids = [item["id"] for item in workloads["workloads"]]
    if type(workloads.get("minimum_repetitions")) is not int or workloads["minimum_repetitions"] < 5:
        raise HarnessError("minimum_repetitions must be at least 5")
    import math
    spread = workloads.get("maximum_spread_pct")
    if type(spread) not in (int, float) or not math.isfinite(spread) or spread < 0:
        raise HarnessError("maximum_spread_pct must be finite and nonnegative")
    for name, rule in workloads["metrics"].items():
        budget = rule.get("max_regression_pct")
        if rule.get("direction") not in {"lower", "higher"} or not rule.get("unit"):
            raise HarnessError(f"{name}: invalid metric direction/unit")
        if rule.get("aggregation", "median") not in {"median", "min", "max"}:
            raise HarnessError(f"{name}: invalid aggregation")
        if type(budget) not in (int, float) or not math.isfinite(budget) or budget < 0:
            raise HarnessError(f"{name}: invalid regression budget")
    if len(workload_ids) != len(set(workload_ids)):
        raise HarnessError("duplicate workload IDs")
    for item in workloads["workloads"]:
        if not item["metrics"] or set(item["metrics"]) - set(workloads["metrics"]):
            raise HarnessError(f"{item['id']}: invalid workload metrics")
    scenario_ids = [item["id"] for item in faults["scenarios"]]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise HarnessError("duplicate fault scenario IDs")
    for item in faults["scenarios"]:
        if not item["invariants"] or set(item["invariants"]) - set(ids):
            raise HarnessError(f"{item['id']}: unknown invariants")
        if type(item["minimum_workers"]) is not int or item["minimum_workers"] < 1:
            raise HarnessError(f"{item['id']}: invalid worker count")


def load(root: Path) -> tuple[dict, dict, dict, dict, dict]:
    values = tuple(read_toml(root / "harness" / name) for name in (
        "policy.toml", "architecture.toml", "invariants.toml", "workloads.toml", "faults.toml"))
    validate_policy(*values)
    return values


def git(root: Path, *args: str, allow_failure: bool = False,
        environment: dict[str, str] | None = None) -> bytes:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=30, env=environment)
    if result.returncode and not allow_failure:
        raise HarnessError(result.stderr.decode(errors="replace").strip())
    return result.stdout if not result.returncode else b""


def changed_paths(root: Path, base: str | None) -> list[str]:
    # Explicit base uses merge-base so PR branch changes are not confused with
    # unrelated commits on the target branch. --no-renames includes both paths.
    if base:
        commit = git(root, "rev-parse", "--verify", "--end-of-options", base + "^{commit}").strip().decode()
        merge = git(root, "merge-base", commit, "HEAD").strip().decode()
        tracked = git(root, "diff", "--no-renames", "--name-only", "-z", merge, "--")
    elif git(root, "rev-parse", "--verify", "HEAD", allow_failure=True):
        tracked = git(root, "diff", "--no-renames", "--name-only", "-z", "HEAD", "--")
    else:
        tracked = git(root, "ls-files", "-z")
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted({normalize_path(p.decode()) for p in (tracked + untracked).split(b"\0") if p})


def plan(root: Path, paths: list[str], policy: dict, architecture: dict,
         invariants: dict) -> dict:
    paths = sorted({normalize_path(path) for path in paths})
    required = set(policy["bootstrap_suites"])
    reasons = {}
    affected = set()
    runtime_changed = False
    has_runtime = any(production_source(path.relative_to(root).as_posix(), policy)
                      for path in files(root, set(policy["ignored_directories"])))
    for path in paths:
        gates = set()
        module = owner(path, architecture)
        documentation = PurePosixPath(path).suffix in {".md", ".rst"}
        operational = (module is not None or path.startswith(("config/", "deploy/", "schemas/", "migrations/"))
                       or PurePosixPath(path).name in {"Dockerfile", "compose.yml", "compose.yaml"})
        if production_source(path, policy) or (operational and not documentation):
            runtime_changed = True
            gates.add("functional")
            if module:
                affected.add(module)
            if module not in {"cli", "mcp", "client-api"}:
                gates.update({"performance-smoke", "stability-component"})
            if path.endswith(".rs"):
                gates.add("rust")
        if not documentation:
            # Component drivers are a real, bounded gate for the current slice.
            # Full registries remain required for release and their own drivers.
            for prefix, suite in (("tests/functional/", "functional"), ("tests/integration/", "functional"),
                                  ("tests/compatibility/", "functional"), ("tests/soak/", "soak")):
                if path.startswith(prefix):
                    gates.add(suite)
            for prefix, component, full in (("tests/performance/", "performance-smoke", "performance"),
                                            ("benchmarks/", "performance-smoke", "performance"),
                                            ("tests/faults/", "stability-component", "stability")):
                if path.startswith(prefix):
                    gates.add(component if path.startswith(prefix + "component/") else full)
        dependency_change = (PurePosixPath(path).name in {
            "Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "requirements-m0.lock"}
            or path in {"scripts/cargo.py", "scripts/m0.py"} or path.startswith("scripts/m0lib/"))
        if dependency_change:
            runtime_changed = True
            gates.update({"rust", "functional", "performance-smoke", "stability-component"})
        if path.startswith("api/") and has_runtime:
            gates.update({"functional", "performance-smoke", "stability-component"})
        if gates:
            reasons[path] = sorted(gates)
            required.update(gates)
    impacted = set(affected)
    while True:
        downstream = {name for name, module in architecture["modules"].items()
                      if impacted.intersection(module["allowed"])}
        if downstream.issubset(impacted):
            break
        impacted.update(downstream)
    relevant = [item["id"] for item in invariants["invariants"]
                if impacted.intersection(item["modules"])]
    return {"changed_paths": paths, "affected_modules": sorted(affected),
            "impacted_modules": sorted(impacted), "impact_model": "conservative reverse allowed-module DAG",
            "required_suites": sorted(required), "reasons": reasons,
            "invariants": relevant, "runtime_present": has_runtime,
            "runtime_changed": runtime_changed}
