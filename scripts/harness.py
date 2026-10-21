#!/usr/bin/env python3
"""One entry point for planning, checks, architecture and evidence validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from harnesslib.architecture import lint
from harnesslib.evidence import compare_performance, read_json, verify_stability
from harnesslib.policy import HarnessError, load, plan
from harnesslib.runner import check, discover_changes
from harnesslib.validation import LEVELS
from harnesslib.validation_binding import bound_plan
from harnesslib.validation_registry import load_registry
from harnesslib.version_control import checkpoint, install_hooks, recover, require_committable_tree, status
from harnesslib.task_state import read_task
from harnesslib.workflow import abandon_task, finish_task, start_task

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("lint", help="validate policies, source ownership and Cargo module edges")
    planner = commands.add_parser("plan", help="classify changes; planning is not test evidence")
    planner.add_argument("--base", default="auto")
    planner.add_argument("--path", action="append", help="advisory plan for a repository-relative path")
    for target in (planner,):
        target.add_argument("--level", choices=LEVELS, default="auto")
        target.add_argument("--module", action="append", default=[])
    checker = commands.add_parser("check", help="run required gates and write logs/JSON")
    checker.add_argument("--scope", choices=("bootstrap", "change", "release"), default="change")
    checker.add_argument("--base", default="auto")
    checker.add_argument("--level", choices=LEVELS, default="auto")
    checker.add_argument("--module", action="append", default=[])
    checker.add_argument("--batch", help="stable integration batch identifier; recorded, never a cache key")
    performance = commands.add_parser("compare-performance")
    performance.add_argument("--baseline", type=Path, required=True)
    performance.add_argument("--candidate", type=Path, required=True)
    stability = commands.add_parser("verify-stability")
    stability.add_argument("--report", type=Path, required=True)
    commands.add_parser("git-status", help="show commit, dirty state and recovery checkpoints")
    commands.add_parser("install-git-hooks", help="enable repository hooks without replacing custom hooks")
    commands.add_parser("pre-commit", help="check the staged snapshot and run change quality gates")
    snapshot = commands.add_parser("checkpoint", help="tag a clean committed recovery point")
    snapshot.add_argument("--label", required=True)
    snapshot.add_argument("--report", type=Path)
    recovery = commands.add_parser("recover", help="open a checkpoint in a new detached worktree")
    recovery.add_argument("--checkpoint", required=True)
    recovery.add_argument("--destination", type=Path, required=True)
    starter = commands.add_parser("task-start", help="record a clean task base and create a recovery checkpoint")
    starter.add_argument("--label", required=True)
    starter.add_argument("--objective", required=True)
    commands.add_parser("task-status", help="read the worktree-local task receipt")
    finish = commands.add_parser("task-finish", help="verify task-wide evidence and archive its logs")
    finish.add_argument("--report", type=Path, required=True)
    finish.add_argument("--review", required=True)
    abandon = commands.add_parser("task-abandon", help="record a stopped task without changing Git/files")
    abandon.add_argument("--reason", required=True)
    arguments = parser.parse_args()
    try:
        # Recovery must still work when the current policy is broken.
        if arguments.command in {"git-status", "install-git-hooks", "recover", "task-status", "task-abandon"}:
            if arguments.command == "git-status":
                result = status(ROOT)
            elif arguments.command == "install-git-hooks":
                result = install_hooks(ROOT)
            elif arguments.command == "task-status":
                result = read_task(ROOT)
            elif arguments.command == "task-abandon":
                result = abandon_task(ROOT, arguments.reason)
            else:
                result = recover(ROOT, arguments.checkpoint, arguments.destination)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        configuration = load(ROOT)
        policy, architecture, invariants, workloads, faults = configuration
        if arguments.command == "lint":
            load_registry(ROOT, policy, architecture)
            for message in lint(ROOT, policy, architecture):
                print("OK:", message)
            print("Runtime invariants are registered obligations, not proven by this lint.")
        elif arguments.command == "plan":
            paths = arguments.path if arguments.path is not None else discover_changes(ROOT, arguments.base)
            selected = bound_plan(ROOT, paths, policy, architecture, invariants, arguments.level, arguments.module)
            output = {**selected["legacy_impact"], "validation": selected}
            print(json.dumps(output, ensure_ascii=False, indent=2))
        elif arguments.command in {"check", "pre-commit"}:
            if arguments.command == "pre-commit":
                require_committable_tree(ROOT)
                arguments.scope, arguments.base = "change", "auto"
                arguments.level, arguments.module, arguments.batch = "auto", [], None
            report, path = check(ROOT, arguments.scope, arguments.base, configuration,
                                 arguments.level, arguments.module, arguments.batch)
            if arguments.command == "pre-commit":
                require_committable_tree(ROOT)
                if status(ROOT)["head"] != report["git_commit"]:
                    raise HarnessError("HEAD changed during pre-commit checks; inspect and retry")
            for item in report["results"]:
                print(f"{item['status'].upper()}: {item['suite']} {item.get('reason', '')}".rstrip())
            print("Validation:", report["validation"]["profile"]["level"], report["validation"]["profile_sha256"])
            print(f"Report: {path}")
            print("Unimplemented product gates:", ", ".join(report["unimplemented_suites"]) or "none")
            return 0 if report["passed"] else 1
        elif arguments.command == "compare-performance":
            result = compare_performance(read_json(arguments.baseline), read_json(arguments.candidate), workloads)
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
            return 0 if result["passed"] else 1
        elif arguments.command == "verify-stability":
            result = verify_stability(read_json(arguments.report), faults, arguments.report.parent)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif arguments.command == "checkpoint":
            print(json.dumps(checkpoint(ROOT, arguments.label, policy, arguments.report, configuration), ensure_ascii=False, indent=2))
        elif arguments.command == "task-start":
            print(json.dumps(start_task(ROOT, arguments.label, arguments.objective, configuration), ensure_ascii=False, indent=2))
        elif arguments.command == "task-finish":
            print(json.dumps(finish_task(ROOT, arguments.report, arguments.review, configuration), ensure_ascii=False, indent=2))
        return 0
    except (HarnessError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"HARNESS ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
