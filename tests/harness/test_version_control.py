from contextlib import redirect_stdout
import copy
import io
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
from harnesslib.policy import HarnessError, load
from harnesslib.runner import check
from harnesslib.version_control import checkpoint, install_hooks, recover, require_committable_tree, status
import harness


class VersionControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repository"
        self.root.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Harness Test")
        self.git("config", "user.email", "harness@example.invalid")
        self.policy = load(ROOT)[0]
        (self.root / ".gitignore").write_text("artifacts/\n")
        self.configuration = copy.deepcopy(load(ROOT))
        self.configuration[0]["bootstrap_suites"] = ["fixture"]
        self.configuration[0]["suites"]["fixture"] = {"state": "ready", "timeout_seconds": 5,
                                                        "commands": [["{python}", "-c", "print('fixture')"]]}

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True).stdout.decode().strip()

    def commit(self):
        (self.root / "file.txt").write_text("baseline\n")
        self.git("add", "file.txt", ".gitignore")
        self.git("commit", "-m", "fixture baseline")

    def test_checkpoint_rejects_unborn_dirty_and_invalid_labels(self):
        with self.assertRaises(HarnessError):
            checkpoint(self.root, "before-task", self.policy)
        self.commit()
        for label in ("../bad", "-option", "spaces here"):
            with self.assertRaises(HarnessError):
                checkpoint(self.root, label, self.policy)
        (self.root / "untracked.txt").write_text("preserve me")
        with self.assertRaises(HarnessError):
            checkpoint(self.root, "before-task", self.policy)

    def test_recovery_preserves_dirty_original_and_refuses_existing_destination(self):
        self.commit()
        result = checkpoint(self.root, "before-task", self.policy)
        (self.root / "file.txt").write_text("failed attempt\n")
        (self.root / "untracked.txt").write_text("user work\n")
        target = self.root.parent / "recovered"
        with patch.dict(os.environ, {"GIT_INDEX_FILE": ".git/index"}):
            restored = recover(self.root, result["checkpoint"], target)
        self.assertEqual(restored["commit"], result["commit"])
        self.assertEqual((target / "file.txt").read_text(), "baseline\n")
        self.assertEqual((self.root / "file.txt").read_text(), "failed attempt\n")
        self.assertTrue((self.root / "untracked.txt").exists())
        self.assertFalse(status(self.root)["clean"])
        for reference, destination in ((result["checkpoint"], target), ("HEAD", self.root.parent / "bad"),
                                       (result["checkpoint"], self.root / "nested")):
            with self.assertRaises(HarnessError):
                recover(self.root, reference, destination)

    def test_evidence_must_match_commit_digest_and_passed_state(self):
        self.commit()
        with patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
            report, path = check(self.root, "change", None, self.configuration)
        for field, value in (("passed", False), ("git_commit", "0" * 40), ("checkout_digest", "bad")):
            path.write_text(json.dumps({**report, field: value}))
            with self.assertRaises(HarnessError):
                checkpoint(self.root, "verified", self.policy, path, self.configuration)
        path.write_text(json.dumps(report))
        result = checkpoint(self.root, "verified", self.policy, path, self.configuration)
        self.assertEqual(result["quality"], "selected_gates_passed")
        self.assertIn(result["checkpoint"], status(self.root)["checkpoints"])
        self.assertTrue((Path(result["evidence_directory"]) / "report.json").is_file())

    def test_pre_commit_rejects_unstaged_and_untracked_not_staged_snapshot(self):
        self.commit()
        (self.root / "file.txt").write_text("change\n")
        with self.assertRaises(HarnessError):
            require_committable_tree(self.root)
        self.git("add", "file.txt")
        require_committable_tree(self.root)
        (self.root / "other.txt").write_text("untracked\n")
        with self.assertRaises(HarnessError):
            require_committable_tree(self.root)

    def test_hook_install_is_idempotent_and_preserves_custom_hook_path(self):
        hooks = self.root / ".githooks"
        hooks.mkdir()
        (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
        (hooks / "pre-commit").chmod(0o755)
        install_hooks(self.root)
        install_hooks(self.root)
        self.assertEqual(self.git("config", "--get", "core.hooksPath"), ".githooks")
        self.git("config", "core.hooksPath", "custom-hooks")
        with self.assertRaises(HarnessError):
            install_hooks(self.root)
        self.assertEqual(self.git("config", "--get", "core.hooksPath"), "custom-hooks")

    def test_global_hook_path_is_preserved(self):
        global_config = self.root.parent / "global-gitconfig"
        global_config.write_text("[core]\n    hooksPath = global-hooks\n")
        with patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(global_config)}):
            with self.assertRaises(HarnessError):
                install_hooks(self.root)
            self.assertEqual(self.git("config", "--get", "core.hooksPath"), "global-hooks")

    @unittest.skipUnless(os.name == "posix", "Git executable hook mode on POSIX")
    def test_non_executable_hook_cannot_claim_installation(self):
        hook = self.root / ".githooks/pre-commit"
        hook.parent.mkdir()
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o644)
        with self.assertRaises(HarnessError):
            install_hooks(self.root)

    def test_recovery_cli_does_not_depend_on_current_policy_being_valid(self):
        self.commit()
        point = checkpoint(self.root, "before-task", self.policy)
        directory = self.root / "harness"
        directory.mkdir()
        (directory / "policy.toml").write_text("broken toml [\n")
        destination = self.root.parent / "policy-recovery"
        argv = ["harness.py", "recover", "--checkpoint", point["checkpoint"],
                "--destination", str(destination)]
        with patch.object(harness, "ROOT", self.root), patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
            self.assertEqual(harness.main(), 0)
        self.assertEqual((destination / "file.txt").read_text(), "baseline\n")


if __name__ == "__main__":
    unittest.main()
