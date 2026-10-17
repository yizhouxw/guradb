from pathlib import Path
import re
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from harnesslib.policy import load, plan


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

    def test_job_deadline_can_fit_serial_gate_deadlines_and_evidence_upload(self):
        configuration = load(ROOT)
        policy = configuration[0]
        expression = self.workflow["jobs"]["quality"]["timeout-minutes"]
        match = re.fullmatch(r"\$\{\{ inputs.scope == 'release' && (\d+) \|\| (\d+) \}\}", expression)
        self.assertIsNotNone(match)
        budgets = {"release": int(match[1]) * 60, "change": int(match[2]) * 60}
        selected = plan(ROOT, ["Cargo.toml", "modules/storage/src/lib.rs"], *configuration[:3])
        for scope, names in (("change", selected["required_suites"]), ("release", policy["release_suites"])):
            worst_case = sum(policy["suites"][name]["timeout_seconds"] *
                             max(1, len(policy["suites"][name]["commands"])) for name in names)
            self.assertGreaterEqual(budgets[scope], worst_case + 600, scope)


if __name__ == "__main__":
    unittest.main()
