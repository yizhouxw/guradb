"""Strict performance comparison and fault-evidence validation, not drivers."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median

from .policy import HarnessError


def read_json(path: Path) -> dict:
    def pairs(items: list[tuple]) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise HarnessError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid(value: str) -> None:
        raise HarnessError(f"non-finite JSON number: {value}")

    value = json.loads(path.read_text(), object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(value, dict):
        raise HarnessError("evidence root must be an object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_header(report: dict, kind: str) -> None:
    if type(report.get("schema_version")) is not int or report["schema_version"] != 1 or report.get("kind") != kind:
        raise HarnessError(f"expected {kind} evidence schema v1")
    if report.get("provenance") != "engine":
        raise HarnessError("real engine evidence required; synthetic/demo results are not quality evidence")
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", report.get("git_commit", "")):
        raise HarnessError("missing exact git_commit")
    for key in ("checkout_digest", "workload_digest", "dataset_digest", "dependency_lock_digest"):
        if not re.fullmatch(r"[0-9a-f]{64}", report.get(key, "")):
            raise HarnessError(f"missing SHA-256 {key}")
    environment = report.get("environment")
    required = {"hardware", "os", "toolchain", "topology", "object_store"}
    if not isinstance(environment, dict) or not required.issubset(environment):
        raise HarnessError("incomplete environment fingerprint")
    if any(not isinstance(value, str) or not value.strip() for value in environment.values()):
        raise HarnessError("environment values must be nonempty fingerprints")
    if report.get("correctness_passed") is not True:
        raise HarnessError("correctness must pass before performance/stability evidence is usable")


def compare_performance(baseline: dict, candidate: dict, registry: dict) -> dict:
    for report in (baseline, candidate):
        validate_header(report, "performance")
    identity = ("workload_id", "workload_digest", "dataset_digest", "environment", "parameters")
    for key in identity:
        if key not in baseline or baseline[key] != candidate.get(key):
            raise HarnessError(f"incomparable benchmark context: {key}")
    parameters = baseline["parameters"]
    if not isinstance(parameters, dict) or not {"cache_mode", "concurrency", "seed"}.issubset(parameters):
        raise HarnessError("parameters require cache_mode, concurrency and seed")
    if parameters["cache_mode"] not in {"cold", "warm", "partial", "over-capacity"}:
        raise HarnessError("invalid cache_mode")
    if type(parameters["concurrency"]) is not int or parameters["concurrency"] < 1:
        raise HarnessError("invalid concurrency")
    if type(parameters["seed"]) is not int:
        raise HarnessError("seed must be an integer")
    workloads = {item["id"]: item for item in registry["workloads"]}
    workload = workloads.get(baseline["workload_id"])
    if workload is None:
        raise HarnessError("unregistered workload")
    expected = set(workload["metrics"])
    measurements = []
    for report in (baseline, candidate):
        observed = report.get("metrics")
        if not isinstance(observed, dict) or set(observed) != expected:
            raise HarnessError("metric set must exactly match registered workload (including recall/cost)")
        values = {}
        for name in expected:
            samples = observed[name]
            if not isinstance(samples, list) or len(samples) < registry["minimum_repetitions"]:
                raise HarnessError(f"{name}: insufficient independent repetitions")
            rule = registry["metrics"][name]
            for value in samples:
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise HarnessError(f"{name}: invalid metric value")
                if not rule.get("minimum", 0) <= value <= rule.get("maximum", math.inf):
                    raise HarnessError(f"{name}: metric outside valid range")
            center = median(samples)
            spread = (max(samples) - min(samples)) * 100 / center if center else (0 if max(samples) == 0 else math.inf)
            if spread > registry["maximum_spread_pct"]:
                raise HarnessError(f"{name}: unstable repetitions; preserve report and investigate before rerunning")
            aggregation = rule.get("aggregation", "median")
            values[name] = {"median": median, "min": min, "max": max}[aggregation](samples)
        measurements.append(values)
    comparisons = []
    for name in sorted(expected):
        previous, current = (values[name] for values in measurements)
        rule = registry["metrics"][name]
        difference = current - previous if rule["direction"] == "lower" else previous - current
        regression = 0.0 if difference <= 0 else (100 * difference / previous if previous else math.inf)
        passed = regression <= rule["max_regression_pct"] + 1e-9
        comparisons.append({"metric": name, "aggregation": rule.get("aggregation", "median"),
                            "baseline_value": previous, "candidate_value": current,
                            "regression_pct": regression if math.isfinite(regression) else "infinite",
                            "budget_pct": rule["max_regression_pct"], "passed": passed})
    return {"kind": "performance-comparison", "workload_id": baseline["workload_id"],
            "baseline_commit": baseline["git_commit"], "candidate_commit": candidate["git_commit"],
            "baseline_checkout_digest": baseline["checkout_digest"], "candidate_checkout_digest": candidate["checkout_digest"],
            "workload_digest": baseline["workload_digest"], "dataset_digest": baseline["dataset_digest"],
            "passed": all(item["passed"] for item in comparisons), "comparisons": comparisons,
            "method": "registered aggregation with spread guard; not a statistical significance claim"}


def verify_stability(report: dict, registry: dict, report_directory: Path) -> dict:
    validate_header(report, "stability")
    if report.get("suite_id") != registry["suite_id"]:
        raise HarnessError("wrong fault suite")
    entries = report.get("scenarios")
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise HarnessError("fault scenarios must be objects")
    observed = {item.get("id"): item for item in entries}
    expected = {item["id"]: item for item in registry["scenarios"]}
    if len(observed) != len(entries) or set(observed) != set(expected):
        raise HarnessError("missing, duplicate or unexpected fault scenarios")
    for name, requirement in expected.items():
        item = observed[name]
        if item.get("fault_injected") is not True or item.get("passed") is not True:
            raise HarnessError(f"{name}: injection or invariant checks did not pass")
        if type(item.get("seed")) is not int:
            raise HarnessError(f"{name}: missing replay seed")
        workers = item.get("workers")
        if type(workers) is not int or workers < requirement["minimum_workers"]:
            raise HarnessError(f"{name}: insufficient real worker count")
        checks = item.get("checks", {})
        if not isinstance(checks, dict) or any(checks.get(key) is not True for key in requirement["invariants"]):
            raise HarnessError(f"{name}: invariant evidence incomplete")
        trace = item.get("trace")
        if not isinstance(trace, str) or Path(trace).is_absolute() or ".." in Path(trace).parts:
            raise HarnessError(f"{name}: trace must be a relative evidence file")
        path = (report_directory / trace).resolve()
        if not path.is_relative_to(report_directory.resolve()) or not path.is_file() or path.stat().st_size == 0:
            raise HarnessError(f"{name}: missing/nonlocal trace")
        if item.get("trace_sha256") != sha256(path):
            raise HarnessError(f"{name}: trace digest mismatch")
    return {"kind": "stability-validation", "passed": True, "scenario_count": len(expected),
            "git_commit": report["git_commit"], "checkout_digest": report["checkout_digest"],
            "limitation": "verifies receipts, not trace semantics; real drivers and review remain required"}
