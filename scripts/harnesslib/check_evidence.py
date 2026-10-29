"""Validate check completion and preserve its logs before declaring a checkpoint."""

import hashlib
import json
import math
from pathlib import Path
import re
import sys

from .policy import HarnessError, git, plan
from .runner import checkout_digest, discover_changes
from .validation_binding import bound_plan


def validate_report(root: Path, path: Path, configuration: tuple) -> dict:
    policy, architecture, invariants, _, _ = configuration
    report = json.loads(path.read_text())
    if (not isinstance(report, dict) or type(report.get("schema_version")) is not int
            or report.get("schema_version") not in {1, 2} or report.get("kind") != "harness-check"
            or report.get("passed") is not True or report.get("scope") not in {"bootstrap", "change", "release"}
            or "selection_base" not in report
            or report.get("git_commit") != git(root, "rev-parse", "HEAD").decode().strip()
            or report.get("checkout_digest") != checkout_digest(root, policy)):
        raise HarnessError("report must pass and match current commit, checkout and explicit selection base")
    base = report["selection_base"]
    if base is not None and (not isinstance(base, str) or (base != "all" and not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base))):
        raise HarnessError("invalid report selection base")
    selected = plan(root, discover_changes(root, base), policy, architecture, invariants)
    if report.get("plan") != selected:
        raise HarnessError("report plan does not match actual changes and current policy")
    expected = selected["required_suites"]
    if report["scope"] == "bootstrap":
        expected = policy["bootstrap_suites"]
    elif report["scope"] == "release":
        expected = policy["release_suites"]
        if not selected["runtime_present"]:
            raise HarnessError("release evidence requires runtime implementation")
    suite_map = policy["suites"]
    if report["schema_version"] == 1:
        if any(name in report for name in ("validation", "level", "modules", "profile_sha256", "batch")):
            raise HarnessError("legacy report cannot assert v2 validation claims")
    else:
        expected_keys = {"schema_version", "kind", "scope", "selection_base", "created_at", "git_commit",
                         "checkout_digest", "plan", "results", "unimplemented_suites", "product_quality",
                         "validation", "batch", "passed", "validation_cost"}
        if set(report) != expected_keys:
            raise HarnessError("unknown/missing v2 report field; no extra level claims permitted")
        validation = report.get("validation")
        if not isinstance(validation, dict):
            raise HarnessError("v2 report requires a validation profile")
        requested = validation.get("requested_level")
        modules = validation.get("requested_modules")
        if not isinstance(modules, list) or not all(isinstance(name, str) for name in modules):
            raise HarnessError("v2 report requires explicit requested modules")
        actual = bound_plan(root, discover_changes(root, base), policy, architecture, invariants,
                            requested, modules, report["scope"], validation.get("stage"), validation.get("core_flow"))
        if report.get("product_quality") != "only_" + actual["profile"]["level"] + "_profile":
            raise HarnessError("v2 quality claim cannot promote its validation level")
        if validation != actual:
            raise HarnessError("validation level/profile/source denominator does not match current closure")
        batch = report.get("batch")
        if batch is not None and (not isinstance(batch, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", batch)):
            raise HarnessError("invalid report batch")
        suite_map = actual["profile"]["suites"]
        expected = list(suite_map)
    results = report.get("results", [])
    if (not isinstance(results, list) or not results or not all(isinstance(item, dict) for item in results)
            or len(results) != len(expected)
            or {item.get("suite") for item in results} != set(expected)):
        raise HarnessError("report missing required suites or containing duplicate/extra results")
    if report["schema_version"] == 2 and [item["suite"] for item in results] != actual["profile"]["suite_order"]:
        raise HarnessError("v2 result order must match the bound execution profile")
    for item in results:
        suite = suite_map[item["suite"]]
        commands = item.get("commands", [])
        if (item.get("status") != "passed" or suite["state"] != "ready"
                or not isinstance(commands, list) or len(commands) != len(suite["commands"]) or not commands):
            raise HarnessError("suite must have all real commands completed successfully")
        for number, command in enumerate(commands):
            expected_argv = [arg.replace("{python}", sys.executable).replace("{run_dir}", str(path.resolve().parent))
                             for arg in suite["commands"][number]]
            if not isinstance(command, dict) or command.get("argv") != expected_argv:
                raise HarnessError("command argv does not match current policy")
            log = (root / command["log"]).resolve()
            if (command.get("status") != "passed" or type(command.get("returncode")) is not int
                    or command.get("returncode") != 0
                    or not log.is_relative_to(path.resolve().parent) or not log.is_file()
                    or hashlib.sha256(log.read_bytes()).hexdigest() != command.get("log_sha256")):
                raise HarnessError("command failed, log missing/outside run, or log checksum mismatch")
    if report["schema_version"] == 2:
        commands = [command for item in results for command in item["commands"]]
        durations = [command.get("duration_seconds") for command in commands]
        if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in durations):
            raise HarnessError("invalid command cost evidence")
        cost = report["validation_cost"]
        expected_cost = {"fresh_commands": len(commands), "reused_commands": 0,
                         "command_seconds": round(sum(durations), 3),
                         "maximum_command_seconds": actual["profile"]["maximum_command_seconds"],
                         "log_bytes": sum((root/command["log"]).stat().st_size for command in commands)}
        if (not isinstance(cost, dict) or set(cost) != set(expected_cost) | {"wall_seconds"}
                or any(cost.get(name) != value for name, value in expected_cost.items())
                or type(cost["wall_seconds"]) not in (int, float)
                or not math.isfinite(cost["wall_seconds"]) or cost["wall_seconds"] < 0
                or cost["wall_seconds"] < sum(durations) - (len(commands)*0.001 + 0.01)):
            raise HarnessError("cost counters must match actual command/log evidence; reuse is not implemented")
    return report


def archive_report(root: Path, path: Path, report: dict) -> str:
    common = (root / git(root, "rev-parse", "--git-common-dir").decode().strip()).resolve()
    raw = path.read_bytes()
    if json.loads(raw) != report:
        raise HarnessError("report changed before archival")
    destination = common / "guradb" / "evidence" / hashlib.sha256(raw).hexdigest()
    destination.mkdir(parents=True, exist_ok=True)
    content = {"report.json": raw}
    manifest = {}
    for index, result in enumerate(report["results"]):
        for number, command in enumerate(result["commands"]):
            data = (root / command["log"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != command["log_sha256"]:
                raise HarnessError("evidence log changed before archival")
            name = f"suite-{index}-command-{number}.log"
            content[name] = data
            manifest[command["log"]] = {"file": name, "sha256": command["log_sha256"]}
    content["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    for name, data in content.items():
        target = destination / name
        if target.exists():
            if target.read_bytes() != data:
                raise HarnessError("existing evidence archive differs; preserve and inspect it")
        else:
            with target.open("xb") as stream:
                stream.write(data)
    return str(destination)
