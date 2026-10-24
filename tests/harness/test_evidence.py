import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from harnesslib.evidence import compare_performance, read_json, sha256, verify_stability
from harnesslib.policy import HarnessError, load
from harnesslib.check_evidence import validate_report
from harnesslib.runner import check


def report_fixture(kind="performance"):
    # Synthetic numbers live only in unit tests, never in a product baseline.
    return {"schema_version": 1, "kind": kind, "provenance": "engine",
            "git_commit": "a" * 40, "checkout_digest": "b" * 64,
            "workload_digest": "c" * 64, "dataset_digest": "d" * 64, "dependency_lock_digest": "e" * 64,
            "environment": {key: "test-fingerprint" for key in
                            ("hardware", "os", "toolchain", "topology", "object_store")},
            "correctness_passed": True}


class EvidenceTests(unittest.TestCase):
    def test_v1_blocked_obligations_cannot_be_removed_or_invented_as_pass(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
            root = Path(temporary).resolve()
            for args in (["init", "-b", "main"], ["config", "user.name", "Evidence fixture"],
                         ["config", "user.email", "evidence@example.invalid"]):
                subprocess.run(["git", *args], cwd=root, capture_output=True, check=True, timeout=2)
            (root/".gitignore").write_text("artifacts/\n")
            (root/"README.md").write_text("Temporary evidence protocol only\n")
            for args in (["add", "."], ["commit", "-m", "fixture baseline"]):
                subprocess.run(["git", *args], cwd=root, capture_output=True, check=True, timeout=2)
            configuration = copy.deepcopy(load(ROOT))
            policy = configuration[0]
            policy["bootstrap_suites"] = ["a-fail", "z-blocked"]
            policy["suites"]["a-fail"] = {"state": "ready", "timeout_seconds": 2,
                "commands": [["{python}", "-c", "print('original failure', flush=True); raise SystemExit(7)"]]}
            policy["suites"]["z-blocked"] = {"state": "ready", "timeout_seconds": 2,
                "commands": [["{python}", "-c", "from pathlib import Path; Path('artifacts/forbidden').touch()"]]}
            report, path = check(root, "change", None, configuration)
            self.assertEqual(report["schema_version"], 1)
            self.assertFalse(report["passed"])
            self.assertFalse((root/"artifacts/forbidden").exists())
            failed, blocked = report["results"]
            original = failed["commands"][0]
            log = root/original["log"]
            self.assertIn("original failure", log.read_text())
            self.assertEqual(hashlib.sha256(log.read_bytes()).hexdigest(), original["log_sha256"])
            self.assertEqual(blocked["status"], "blocked")
            self.assertNotIn("commands", blocked)
            for attack in ("passed", "drop-blocked", "invent-blocked-pass"):
                value = copy.deepcopy(report)
                value["passed"] = True
                if attack == "drop-blocked":
                    value["results"].pop()
                if attack == "invent-blocked-pass":
                    # Even forging prefix status cannot supply the unexecuted
                    # command's required real log/identity; no fake log is written.
                    value["results"][0]["status"] = "passed"
                    value["results"][0]["commands"][0].update(status="passed", returncode=0)
                    value["results"][1].update(status="passed", commands=[{
                        "argv": blocked["not_run"][0]["argv"], "status": "passed", "returncode": 0,
                        "log": str(path.parent/"never-executed.log"), "log_sha256": "0"*64}])
                path.write_text(json.dumps(value))
                with self.subTest(attack=attack), self.assertRaises(HarnessError):
                    validate_report(root, path, configuration)
            path.write_text(json.dumps(report))
            self.assertEqual(list(path.parent.glob("*.log")), [log])

    def setUp(self):
        *_, self.workloads, self.faults = load(ROOT)
        self.baseline = dict(report_fixture(), workload_id="retrieval.hybrid",
                             parameters={"cache_mode": "cold", "concurrency": 4, "seed": 42})
        names = self.workloads["workloads"][0]["metrics"]
        self.baseline["metrics"] = {name: [0.98 if name == "recall_at_10" else 100] * 5 for name in names}

    def compare(self, candidate):
        return compare_performance(self.baseline, candidate, self.workloads)

    def test_noisy_repetitions_are_inconclusive_instead_of_a_green_median(self):
        candidate = copy.deepcopy(self.baseline)
        candidate["metrics"]["latency_p95_ms"] = [100, 100, 100, 100, 900]
        with self.assertRaisesRegex(HarnessError, "unstable"):
            self.compare(candidate)

    def test_recall_uses_worst_repetition_not_median(self):
        candidate = copy.deepcopy(self.baseline)
        candidate["metrics"]["recall_at_10"] = [0.90, 0.98, 0.98, 0.98, 0.98]
        self.assertFalse(self.compare(candidate)["passed"])

    def test_faster_latency_cannot_hide_recall_or_get_regression(self):
        for name, value in (("recall_at_10", 0.90), ("object_get_count", 120), ("latency_p99_ms", 120)):
            candidate = copy.deepcopy(self.baseline)
            candidate["metrics"]["latency_p95_ms"] = [50] * 5
            candidate["metrics"][name] = [value] * 5
            with self.subTest(metric=name):
                self.assertFalse(self.compare(candidate)["passed"])

    def test_throughput_regression_direction(self):
        baseline = copy.deepcopy(self.baseline)
        baseline["workload_id"] = "training.scan"
        baseline["metrics"] = {key: [100] * 5 for key in self.workloads["workloads"][1]["metrics"]}
        candidate = copy.deepcopy(baseline)
        candidate["metrics"]["throughput_samples_s"] = [94] * 5
        self.assertFalse(compare_performance(baseline, candidate, self.workloads)["passed"])

    def test_incomparable_context_is_not_a_pass(self):
        for key, value in (("dataset_digest", "e" * 64), ("environment", {"hardware": "different"}),
                           ("parameters", {"cache_mode": "warm", "concurrency": 4, "seed": 42})):
            candidate = copy.deepcopy(self.baseline)
            candidate[key] = value
            with self.subTest(key=key), self.assertRaises(HarnessError):
                self.compare(candidate)

    def test_synthetic_missing_metrics_short_runs_nan_and_bool_are_rejected(self):
        mutations = (
            lambda item: item.update(provenance="synthetic"),
            lambda item: item.update(correctness_passed=False),
            lambda item: item["metrics"].pop("recall_at_10"),
            lambda item: item["metrics"].update(bytes_read=[1]),
            lambda item: item["metrics"].update(bytes_read=[float("nan")] * 5),
            lambda item: item["metrics"].update(bytes_read=[True] * 5),
        )
        for mutate in mutations:
            candidate = copy.deepcopy(self.baseline)
            mutate(candidate)
            with self.assertRaises(HarnessError):
                self.compare(candidate)

    def test_zero_cost_baseline_cannot_hide_new_cost(self):
        self.baseline["metrics"]["object_get_count"] = [0] * 5
        candidate = copy.deepcopy(self.baseline)
        candidate["metrics"]["object_get_count"] = [1] * 5
        self.assertFalse(self.compare(candidate)["passed"])

    def stability_fixture(self, directory):
        trace = directory / "trace.log"
        trace.write_text("synthetic unit-test trace, not an engine run\n")
        report = dict(report_fixture("stability"), suite_id=self.faults["suite_id"], scenarios=[])
        for item in self.faults["scenarios"]:
            report["scenarios"].append({"id": item["id"], "seed": 42, "workers": item["minimum_workers"],
                                        "fault_injected": True, "passed": True,
                                        "checks": {key: True for key in item["invariants"]},
                                        "trace": "trace.log", "trace_sha256": sha256(trace)})
        return report

    def test_fault_evidence_requires_injection_replay_invariants_and_real_trace(self):
        mutations = (
            lambda report: report["scenarios"].pop(),
            lambda report: report["scenarios"][0].update(fault_injected=False),
            lambda report: report["scenarios"][0].update(workers=0),
            lambda report: report["scenarios"][0].update(checks={}),
            lambda report: report["scenarios"][0].update(trace="../escape.log"),
            lambda report: report["scenarios"][0].update(trace_sha256="0" * 64),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self.stability_fixture(root)
            self.assertTrue(verify_stability(report, self.faults, root)["passed"])
            for mutate in mutations:
                invalid = copy.deepcopy(report)
                mutate(invalid)
                with self.assertRaises(HarnessError):
                    verify_stability(invalid, self.faults, root)

    def test_duplicate_json_keys_and_nonfinite_numbers_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            for content in ('{"passed": false, "passed": true}', '{"value": NaN}'):
                path.write_text(content)
                with self.assertRaises(HarnessError):
                    read_json(path)


if __name__ == "__main__":
    unittest.main()
