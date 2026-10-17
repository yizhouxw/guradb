"""Validate check completion and preserve its logs before declaring a checkpoint."""

import hashlib
import json
from pathlib import Path
import re
import sys

from .policy import HarnessError, git, plan
from .runner import checkout_digest, discover_changes


def validate_report(root: Path, path: Path, configuration: tuple) -> dict:
    policy, architecture, invariants, _, _ = configuration
    report = json.loads(path.read_text())
    if (not isinstance(report, dict) or type(report.get("schema_version")) is not int
            or report.get("schema_version") != 1 or report.get("kind") != "harness-check"
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
    results = report.get("results", [])
    if (not isinstance(results, list) or not results or not all(isinstance(item, dict) for item in results)
            or len(results) != len(expected)
            or {item.get("suite") for item in results} != set(expected)):
        raise HarnessError("report missing required suites or containing duplicate/extra results")
    for item in results:
        suite = policy["suites"][item["suite"]]
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
