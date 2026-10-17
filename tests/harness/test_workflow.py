import copy
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
from harnesslib.check_evidence import validate_report
from harnesslib.policy import HarnessError, load
from harnesslib.runner import check, discover_changes
from harnesslib.task_state import read_task, state_path, task_lock
from harnesslib.workflow import abandon_task, finish_task, start_task


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.environment = patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Harness Test")
        self.git("config", "user.email", "harness@example.invalid")
        (self.root / ".gitignore").write_text("artifacts/\n")
        (self.root / "change.txt").write_text("baseline\n")
        self.git("add", ".gitignore", "change.txt")
        self.git("commit", "-m", "baseline")
        self.config = copy.deepcopy(load(ROOT))
        self.config[0]["bootstrap_suites"] = ["fixture"]
        self.config[0]["suites"]["fixture"] = {"state": "ready", "timeout_seconds": 5,
                                                "commands": [["{python}", "-c", "print('real tool fixture')"]]}

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True).stdout.decode().strip()

    def change(self):
        (self.root / "change.txt").write_text("implemented slice\n")
        self.git("add", "change.txt")
        self.git("commit", "-m", "slice")

    def test_task_base_survives_commit_and_completion_archives_logs(self):
        started = start_task(self.root, "test-flow", "verify traceability", self.config)
        self.change()
        self.assertIn("change.txt", discover_changes(self.root, "auto"))
        report, path = check(self.root, "change", "auto", self.config)
        self.assertEqual(report["selection_base"], started["base_commit"])
        result = finish_task(self.root, path, "separate review; tool fixture only", self.config)
        self.assertEqual(result["status"], "completed")
        archived = Path(result["evidence_directory"])
        self.assertEqual(json.loads((archived / "report.json").read_text()), report)
        self.assertTrue((archived / "manifest.json").is_file())
        self.assertEqual(read_task(self.root)["final_commit"], self.git("rev-parse", "HEAD"))

    def test_task_refuses_duplicate_dirty_and_branch_switch(self):
        started = start_task(self.root, "test-flow", "objective", self.config)
        with self.assertRaises(HarnessError):
            start_task(self.root, "second", "objective", self.config)
        self.git("checkout", "-b", "other")
        with self.assertRaises(HarnessError):
            discover_changes(self.root, "auto")
        self.git("checkout", started["branch"])
        (self.root / "user.txt").write_text("preserve this\n")
        stopped = abandon_task(self.root, "blocked; preserve working file and inspect baseline")
        self.assertEqual(stopped["status"], "abandoned")
        self.assertEqual((self.root / "user.txt").read_text(), "preserve this\n")
        with self.assertRaises(HarnessError):
            start_task(self.root, "dirty", "objective", self.config)

    def test_completion_rejects_bootstrap_and_empty_diff_report(self):
        start_task(self.root, "test-flow", "objective", self.config)
        self.change()
        for scope, base in (("bootstrap", "auto"), ("change", None)):
            with self.subTest(scope=scope, base=base):
                _, path = check(self.root, scope, base, self.config)
                with self.assertRaises(HarnessError):
                    finish_task(self.root, path, "reviewed", self.config)
        self.assertEqual(read_task(self.root)["status"], "active")

    def test_report_rejects_missing_failed_commands_plan_and_tampered_logs(self):
        report, path = check(self.root, "change", None, self.config)
        mutations = [
            lambda value: value.update(results=[]),
            lambda value: value["results"].append(copy.deepcopy(value["results"][0])),
            lambda value: value["results"][0].update(status="failed"),
            lambda value: value["results"][0].update(commands=[]),
            lambda value: value["results"][0]["commands"][0].update(returncode=1),
            lambda value: value["results"][0]["commands"][0].update(argv=["true"]),
            lambda value: value["results"][0]["commands"][0].update(log="/etc/passwd"),
            lambda value: value["plan"].update(required_suites=[]),
        ]
        for mutate in mutations:
            value = copy.deepcopy(report)
            mutate(value)
            path.write_text(json.dumps(value))
            with self.assertRaises(HarnessError):
                validate_report(self.root, path, self.config)
        path.write_text(json.dumps(report))
        (self.root / report["results"][0]["commands"][0]["log"]).write_text("altered log")
        with self.assertRaises(HarnessError):
            validate_report(self.root, path, self.config)

    def test_state_is_worktree_local_and_lock_does_not_allow_two_starts(self):
        start_task(self.root, "test-flow", "objective", self.config)
        destination = self.root.parent / "another"
        self.git("worktree", "add", "-b", "separate", str(destination))
        self.assertIsNone(read_task(destination))
        with task_lock(self.root), self.assertRaises(HarnessError):
            abandon_task(self.root, "conflicting operation")
        self.assertTrue(state_path(self.root, "tasks/" + read_task(self.root)["id"] + ".json").is_file())


if __name__ == "__main__":
    unittest.main()
