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

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("lint", help="validate policies, source ownership and Cargo module edges")
    planner = commands.add_parser("plan", help="classify changes; planning is not test evidence")
    planner.add_argument("--base", default="auto")
    planner.add_argument("--path", action="append", help="advisory plan for a repository-relative path")
    checker = commands.add_parser("check", help="run required gates and write logs/JSON")
    checker.add_argument("--scope", choices=("bootstrap", "change", "release"), default="change")
    checker.add_argument("--base", default="auto")
    performance = commands.add_parser("compare-performance")
    performance.add_argument("--baseline", type=Path, required=True)
    performance.add_argument("--candidate", type=Path, required=True)
    stability = commands.add_parser("verify-stability")
    stability.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        configuration = load(ROOT)
        policy, architecture, invariants, workloads, faults = configuration
        if arguments.command == "lint":
            for message in lint(ROOT, policy, architecture):
                print("OK:", message)
            print("Runtime invariants are registered obligations, not proven by this lint.")
        elif arguments.command == "plan":
            paths = arguments.path if arguments.path is not None else discover_changes(ROOT, arguments.base)
            print(json.dumps(plan(ROOT, paths, policy, architecture, invariants), ensure_ascii=False, indent=2))
        elif arguments.command == "check":
            report, path = check(ROOT, arguments.scope, arguments.base, configuration)
            for item in report["results"]:
                print(f"{item['status'].upper()}: {item['suite']} {item.get('reason', '')}".rstrip())
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
        return 0
    except (HarnessError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"HARNESS ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
