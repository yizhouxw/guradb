import copy
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from harnesslib.policy import load
from harnesslib.runner import check, run_command
from harnesslib.validation_binding import bound_plan


class CIWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.load((ROOT / ".github/workflows/check.yml").read_text(), Loader=yaml.BaseLoader)

    def test_manual_checks_and_tokens_cannot_silently_skip_quality(self):
        workflow = self.workflow
        self.assertEqual(workflow["on"]["workflow_dispatch"]["inputs"]["base"]["default"], "all")
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        job = workflow["jobs"]["quality"]
        for step in job["steps"]:
            if "uses" in step:
                self.assertRegex(step["uses"], r"^[\w./-]+@[0-9a-f]{40}$")
            if "run" in step:
                self.assertNotIn("${{", step["run"], "untrusted input must pass via env and argv")
            self.assertNotEqual(step.get("continue-on-error"), "true")
        run = next(step for step in job["steps"] if step.get("name") == "Run quality harness")
        self.assertIn('--base "$HARNESS_BASE"', run["run"])
        upload = job["steps"][-1]
        self.assertEqual(upload["if"], "always()")
        self.assertIn("matrix.python", upload["with"]["name"])
        self.assertIn("pull_request", job["concurrency"]["cancel-in-progress"])

    def test_levels_preserve_two_jobs_and_stable_system_release_scheduling(self):
        workflow = self.workflow
        job = workflow["jobs"]["quality"]
        self.assertEqual(job["name"], "quality (Python ${{ matrix.python }})")
        self.assertEqual(job["strategy"]["matrix"]["python"], ["3.11", "3.14"])
        self.assertIn("schedule", workflow["on"])
        self.assertIn("system", workflow["on"]["workflow_dispatch"]["inputs"]["level"]["options"])
        self.assertIn("refs/heads/main", job["env"]["HARNESS_LEVEL"])
        self.assertIn("schedule", job["env"]["HARNESS_SCOPE"])
        run = next(step for step in job["steps"] if step.get("name") == "Run quality harness")
        self.assertIn('--level "$HARNESS_LEVEL"', run["run"])
        self.assertIn('--batch "$HARNESS_BATCH"', run["run"])
        self.assertIn("--base", run["run"])

    def assert_job_budgets_fit(self, policy):
        job = self.workflow["jobs"]["quality"]
        self.assertEqual(job["runs-on"], "ubuntu-latest")
        expression = job["timeout-minutes"]
        match = re.fullmatch(r"\$\{\{ \(inputs.scope == 'release' \|\| inputs.level == 'release' \|\| github.event_name == 'schedule'\) && (\d+) \|\| (\d+) \}\}", expression)
        self.assertIsNotNone(match)
        budgets = {"release": int(match[1]) * 60, "change": int(match[2]) * 60}
        # All ready suites conservatively bound any change selection, including
        # Python plus Rust. Planned gates record missing without executing work.
        ready = [name for name, suite in policy["suites"].items() if suite["state"] == "ready"]
        for scope, names in (("change", ready), ("release", policy["release_suites"])):
            self.assertLessEqual(budgets[scope], 360 * 60, "hosted job exceeds the platform hard limit")
            worst_case = sum(policy["suites"][name]["timeout_seconds"] *
                             len(policy["suites"][name]["commands"]) for name in names
                             if policy["suites"][name]["state"] == "ready")
            self.assertGreaterEqual(budgets[scope], worst_case + 600, scope)

    def test_every_registered_profile_fits_the_job_without_reducing_commands_or_upload_margin(self):
        policy, architecture, invariants, *_ = load(ROOT)
        samples = (["README.md"], ["scripts/harness.py"], ["crates/guradb-query/src/lib.rs"],
                   ["crates/guradb-storage/src/lib.rs"],
                   ["crates/guradb-query/src/lib.rs", "crates/guradb-storage/src/lib.rs"],
                   ["api/cf1a/schema.json"])
        ready_worst = sum(suite["timeout_seconds"] * len(suite["commands"])
                          for suite in policy["suites"].values() if suite["state"] == "ready")
        for paths in samples:
            profile = bound_plan(ROOT, paths, policy, architecture, invariants)["profile"]
            self.assertLessEqual(profile["maximum_command_seconds"], ready_worst, paths)
        self.assert_job_budgets_fit(policy)  # once-only 600s remains required.

    def test_job_deadline_can_fit_serial_gate_deadlines_and_evidence_upload(self):
        self.assert_job_budgets_fit(load(ROOT)[0])

    def test_job_above_hosted_hard_limit_is_rejected(self):
        job = self.workflow["jobs"]["quality"]
        job["timeout-minutes"] = re.sub(r"&& \d+ \|\|", "&& 367 ||", job["timeout-minutes"], count=1)
        with self.assertRaisesRegex(AssertionError, "hosted job"):
            self.assert_job_budgets_fit(load(ROOT)[0])

    def test_future_ready_full_gates_are_counted_and_require_a_new_budget(self):
        policy = copy.deepcopy(load(ROOT)[0])
        future = ("performance", "stability", "soak")
        for name in future:
            policy["suites"][name].update(state="ready", commands=[["future-certified-driver", name]])
        ready_seconds = sum(suite["timeout_seconds"] * len(suite["commands"])
                            for suite in policy["suites"].values() if suite["state"] == "ready")
        self.assertGreater(ready_seconds + 600, 360 * 60)
        with self.assertRaises(AssertionError):
            self.assert_job_budgets_fit(policy)

    def test_real_runner_never_executes_planned_release_gate_or_reports_success(self):
        configuration = copy.deepcopy(load(ROOT))
        policy = configuration[0]
        policy["suites"]["smoke"] = {"state": "ready", "timeout_seconds": 5,
                                      "commands": [["{python}", "-c", "print('actual ready gate')"]]}
        policy["release_suites"] = ["smoke", "stability"]
        # The sentinel must never be executed even if a planned entry contains
        # a proposed command. Missing is still a mandatory release failure.
        policy["suites"]["stability"].update(state="planned", reason="fixture full gate missing",
                                                 commands=[["this-must-never-execute"]])
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
            root = Path(directory).resolve()
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            source = root / "modules/storage/fixture.py"
            source.parent.mkdir(parents=True)
            source.write_text("VALUE = 1\n")
            with patch("harnesslib.runner.run_command", wraps=run_command) as execute:
                report, report_path = check(root, "release", None, configuration)
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(execute.call_args.args[0], [sys.executable, "-c", "print('actual ready gate')"])
            self.assertTrue(report["plan"]["runtime_present"])
            self.assertFalse(report["passed"])
            self.assertEqual([(row["suite"], row["status"]) for row in report["results"]],
                             [("smoke", "passed"), ("stability", "missing")])
            self.assertTrue(report_path.is_file())


if __name__ == "__main__":
    unittest.main()
