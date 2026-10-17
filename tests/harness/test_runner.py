import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from harnesslib.policy import load
from harnesslib.runner import check, discover_changes, run_command


class RunnerTests(unittest.TestCase):
    def configuration(self):
        configuration = copy.deepcopy(load(ROOT))
        configuration[0]["bootstrap_suites"] = ["smoke"]
        configuration[0]["suites"]["smoke"] = {
            "state": "ready", "timeout_seconds": 5,
            "commands": [["{python}", "-c", "print('fixture gate')"]]}
        return configuration

    def init(self, root):
        subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)

    def test_exit_failure_missing_tool_and_output_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_command([sys.executable, "-c", "raise SystemExit(7)"], root, root / "fail.log", 2)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["returncode"], 7)
            result = run_command([str(root / "not-a-tool")], root, root / "missing.log", 2)
            self.assertEqual(result["status"], "missing_tool")
            result = run_command([sys.executable, "-c", "print('x' * 5000)"], root, root / "large.log", 2, 1024)
            self.assertEqual(result["status"], "output_limit")
            self.assertLessEqual((root / "large.log").stat().st_size, 1024)

    @unittest.skipUnless(os.name == "posix", "process group cleanup requires POSIX")
    def test_timeout_kills_descendants(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = "import time; from pathlib import Path; time.sleep(.5); Path('leaked').write_text('bad')"
            parent = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(10)"
            result = run_command([sys.executable, "-c", parent], root, root / "timeout.log", .1)
            self.assertEqual(result["status"], "timeout")
            time.sleep(.6)
            self.assertFalse((root / "leaked").exists())

    def test_planned_gate_blocks_runtime_change(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
            root = Path(directory)
            self.init(root)
            source = root / "modules/storage/src/lib.rs"
            source.parent.mkdir(parents=True)
            source.write_text("pub struct Store;\n")
            configuration = self.configuration()
            for name in ["rust", "functional", "performance-smoke", "stability-component"]:
                configuration[0]["suites"][name].update(state="planned", reason="fixture missing runtime", commands=[])
            report, path = check(root, "change", None, configuration)
            self.assertFalse(report["passed"])
            self.assertEqual({item["suite"] for item in report["results"] if item["status"] == "missing"},
                             {"rust", "functional", "performance-smoke", "stability-component"})
            self.assertEqual(json.loads(path.read_text())["checkout_digest"], report["checkout_digest"])

    def test_bootstrap_reports_runtime_gaps_and_release_never_green_without_kernel(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
            root = Path(directory)
            self.init(root)
            configuration = self.configuration()
            report, _ = check(root, "bootstrap", None, configuration)
            self.assertTrue(report["passed"])
            self.assertEqual(report["product_quality"], "not_assessed_by_bootstrap")
            self.assertIn("stability", report["unimplemented_suites"])
            configuration[0]["release_suites"] = ["smoke", "stability"]
            report, _ = check(root, "release", None, configuration)
            self.assertFalse(report["passed"])
            self.assertIn("runtime-present", {item["suite"] for item in report["results"]})

    def test_source_change_during_check_invalidates_report(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
            root = Path(directory)
            self.init(root)
            configuration = self.configuration()
            configuration[0]["suites"]["smoke"]["commands"] = [
                ["{python}", "-c", "from pathlib import Path; Path('changed.txt').write_text('mutation')"]]
            report, _ = check(root, "bootstrap", None, configuration)
            self.assertFalse(report["passed"])
            self.assertEqual(report["results"][-1]["suite"], "checkout-unchanged")

    def test_initial_push_checks_entire_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init(root)
            (root / "Cargo.toml").write_text("[workspace]\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            event = root / "event.json"
            event.write_text(json.dumps({"before": "0" * 40}))
            with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event), "GITHUB_EVENT_NAME": "push"}):
                self.assertIn("Cargo.toml", discover_changes(root, "auto"))

    def test_clean_manual_ci_checks_all_committed_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init(root)
            source = root / "modules/storage/src/lib.rs"
            source.parent.mkdir(parents=True)
            source.write_text("pub struct Store;\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                            "commit", "-m", "fixture"], cwd=root, check=True, capture_output=True)
            event = root / "artifacts/event.json"
            event.parent.mkdir()
            event.write_text("{}")
            with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event), "GITHUB_EVENT_NAME": "workflow_dispatch"}):
                self.assertIn("modules/storage/src/lib.rs", discover_changes(root, "auto"))

    def test_head_change_without_source_mutation_invalidates_evidence(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
            root = Path(directory)
            self.init(root)
            configuration = self.configuration()
            configuration[0]["suites"]["smoke"]["commands"] = [[
                "git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "commit", "--allow-empty", "-m", "change HEAD during check"]]
            report, _ = check(root, "bootstrap", None, configuration)
            self.assertFalse(report["passed"])
            self.assertEqual(report["results"][-1]["suite"], "head-unchanged")


if __name__ == "__main__":
    unittest.main()
