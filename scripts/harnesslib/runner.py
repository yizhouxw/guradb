"""Bounded command execution with durable logs and explicit missing gates."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import uuid4

from .policy import HarnessError, changed_paths, files, git, plan
from .task_state import active_base
from .validation_binding import bound_plan


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def checkout_digest(root: Path, policy: dict) -> str:
    result = hashlib.sha256()
    for path in files(root, set(policy["ignored_directories"])):
        result.update(path.relative_to(root).as_posix().encode() + b"\0")
        result.update(str(path.stat().st_mode & 0o777).encode() + b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                result.update(chunk)
        result.update(b"\0")
    return result.hexdigest()


def stop_group(process: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except PermissionError as denied:
                # A reaped leader can leave a zombie-only group on Darwin.
                # One bounded cleanup grace covers both waitpid and the group;
                # persistent permission denial remains an error.
                deadline = time.monotonic() + 0.1
                try:
                    process.wait(timeout=max(0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    raise denied from None
                while True:
                    if time.monotonic() >= deadline:
                        raise denied from None
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                        break
                    except PermissionError:
                        time.sleep(min(0.005, max(0, deadline - time.monotonic())))
        elif process.poll() is None:
            process.kill()
    except ProcessLookupError:
        pass
    process.wait()


def child_environment(root: Path) -> dict[str, str]:
    # Hooks export worktree-local Git paths. Never leak them into nested fixture
    # repositories: git init/config/commit would otherwise mutate the caller.
    environment = os.environ.copy()
    for name in git(root, "rev-parse", "--local-env-vars").decode().splitlines():
        environment.pop(name, None)
    return environment


def run_command(argv: list[str], root: Path, log: Path, timeout: float,
                max_log_bytes: int = 16 * 1024 * 1024) -> dict:
    started = time.monotonic()
    status = "failed"
    code = None
    process = None
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log.open("wb") as stream:
            process = subprocess.Popen(argv, cwd=root, stdout=stream, stderr=subprocess.STDOUT,
                                       start_new_session=os.name == "posix", env=child_environment(root))
            deadline = started + timeout
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    status = "timeout"
                    break
                if log.stat().st_size > max_log_bytes:
                    status = "output_limit"
                    break
                time.sleep(0.02)
            else:
                code = process.returncode
                status = "passed" if code == 0 else "failed"
            if log.stat().st_size > max_log_bytes:
                status = "output_limit"
    except OSError as error:
        log.write_text(str(error) + "\n")
        status = "missing_tool"
    finally:
        if process is not None:
            stop_group(process)
            code = process.returncode
        if log.exists() and log.stat().st_size > max_log_bytes:
            with log.open("r+b") as stream:
                stream.truncate(max_log_bytes)
    return {"argv": argv, "status": status, "returncode": code,
            "duration_seconds": round(time.monotonic() - started, 3), "log": str(log)}


def selection_base(root: Path, base: str | None) -> str | None:
    if base != "auto":
        if base in {None, "all"}:
            return base
        commit = git(root, "rev-parse", "--verify", "--end-of-options", base + "^{commit}").decode().strip()
        return git(root, "merge-base", commit, "HEAD").decode().strip()
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return active_base(root)
    event = json.loads(Path(event_path).read_text())
    if "pull_request" in event:
        return selection_base(root, event["pull_request"]["base"]["sha"])
    before = event.get("before")
    if before and set(before) == {"0"}:
        return "all"
    if before:
        return selection_base(root, before)
    if os.environ.get("GITHUB_EVENT_NAME") in {"workflow_dispatch", "schedule"}:
        return "all"
    raise HarnessError("unsupported CI event: cannot determine changed paths")


def discover_changes(root: Path, base: str | None) -> list[str]:
    selected = selection_base(root, base)
    if selected == "all":
        raw = git(root, "ls-files", "-z") + git(root, "ls-files", "--others", "--exclude-standard", "-z")
        return sorted({value.decode() for value in raw.split(b"\0") if value})
    return changed_paths(root, selected)


def check(root: Path, scope: str, base: str | None, configuration: tuple,
          level: str | None = None, modules=(), batch: str | None = None,
          stage="auto", core_flow=None) -> tuple[dict, Path]:
    started = time.monotonic()
    root = root.resolve()
    policy, architecture, invariants, _, _ = configuration
    selected_base = selection_base(root, base)
    changes = discover_changes(root, selected_base)
    selected = plan(root, changes, policy, architecture, invariants)
    suites = policy["bootstrap_suites"] if scope == "bootstrap" else selected["required_suites"]
    if scope == "release":
        suites = policy["release_suites"]
    validation = None
    suite_map = policy["suites"]
    if level is not None:
        validation = bound_plan(root, changes, policy, architecture, invariants, level, modules, scope,
                                stage, core_flow)
        suite_map = validation["profile"]["suites"]
        suites = list(suite_map)
    if batch is not None:
        import re
        if validation is None or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", batch):
            raise HarnessError("batch needs a v2 report and a 1..80 character identifier")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    run_directory = root / "artifacts" / "harness" / stamp
    run_directory.mkdir(parents=True)
    digest = checkout_digest(root, policy)
    report = {"schema_version": 1, "kind": "harness-check", "scope": scope, "selection_base": selected_base,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "git_commit": git(root, "rev-parse", "--verify", "HEAD", allow_failure=True).decode().strip() or None,
              "checkout_digest": digest, "plan": selected, "results": [],
              "unimplemented_suites": [name for name, item in policy["suites"].items() if item["state"] == "planned"],
              "product_quality": "not_assessed_by_bootstrap" if scope == "bootstrap" else "only_selected_gates"}
    if validation is not None:
        report.update(schema_version=2, validation=validation, batch=batch,
                      product_quality="only_" + validation["profile"]["level"] + "_profile")
    if (scope == "release" or validation is not None and validation["profile"]["level"] == "release") and not selected["runtime_present"]:
        report["results"].append({"suite": "runtime-present", "status": "missing",
                                  "reason": "no database/client runtime implementation exists"})
    report_path = run_directory / "report.json"
    # Execution evidence contains only the actual prefix. Plans that were never
    # launched live separately, without invented return codes/logs/durations.
    def not_run(suite, first=0):
        return [{"command_index": index,
                 "argv": [arg.replace("{python}", sys.executable).replace("{run_dir}", str(run_directory))
                          for arg in command]}
                for index, command in enumerate(suite["commands"]) if index >= first]

    blocker = next(({"suite": item["suite"], "status": item["status"]}
                    for item in report["results"] if item["status"] != "passed"), None)
    for name in suites:
        suite = suite_map[name]
        if blocker is not None:
            report["results"].append({"suite": name, "status": "blocked", "blocked_by": blocker,
                                      "planned_state": suite["state"], "planned_reason": suite.get("reason"),
                                      "not_run": not_run(suite)})
            write_json(report_path, report)
            continue
        if suite["state"] != "ready" or not suite["commands"]:
            report["results"].append({"suite": name, "status": "missing",
                                      "reason": suite.get("reason", "no executable commands registered"),
                                      "not_run": not_run(suite)})
            blocker = {"suite": name, "status": "missing"}
            write_json(report_path, report)
            continue
        results = []
        for index, command in enumerate(suite["commands"]):
            argv = [arg.replace("{python}", sys.executable).replace("{run_dir}", str(run_directory))
                    for arg in command]
            result = run_command(argv, root, run_directory / f"{name}-{index}.log", suite["timeout_seconds"])
            result["log"] = Path(result["log"]).relative_to(root).as_posix()
            result["log_sha256"] = hashlib.sha256((root / result["log"]).read_bytes()).hexdigest()
            results.append(result)
            if result["status"] != "passed":
                blocker = {"suite": name, "command_index": index, "status": result["status"]}
                break
        passed = all(result["status"] == "passed" for result in results)
        row = {"suite": name, "status": "passed" if passed else "failed", "commands": results}
        if not passed:
            row.update(blocked_by=blocker, not_run=not_run(suite, len(results)))
        report["results"].append(row)
        write_json(report_path, report)
    if validation is not None:
        try:
            after = bound_plan(root, discover_changes(root, selected_base), policy, architecture,
                               invariants, level, modules, scope, stage, core_flow)
            unchanged = after == validation
        except (HarnessError, OSError):
            unchanged = False
        if not unchanged:
            report["results"].append({"suite": "validation-unchanged", "status": "failed",
                                      "reason": "selection logic/profile/source closure changed while checks ran"})
    if checkout_digest(root, policy) != digest:
        report["results"].append({"suite": "checkout-unchanged", "status": "failed",
                                  "reason": "source/config changed while checks ran; run again"})
    if git(root, "rev-parse", "--verify", "HEAD", allow_failure=True).decode().strip() != (report["git_commit"] or ""):
        report["results"].append({"suite": "head-unchanged", "status": "failed",
                                  "reason": "HEAD changed while checks ran; inspect task base and rerun"})
    report["passed"] = all(item["status"] == "passed" for item in report["results"])
    if validation is not None:
        commands = [command for item in report["results"] for command in item.get("commands", [])]
        report["validation_cost"] = {"fresh_commands": len(commands), "reused_commands": 0,
            "command_seconds": round(sum(item["duration_seconds"] for item in commands), 3),
            "wall_seconds": round(time.monotonic()-started, 3),
            "log_bytes": sum((root/item["log"]).stat().st_size for item in commands),
            "maximum_command_seconds": validation["profile"]["maximum_command_seconds"]}
    write_json(report_path, report)
    return report, report_path
