import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from harnesslib.policy import load
from harnesslib.runner import check, discover_changes, run_command
from harnesslib.validation_binding import LOGIC_INPUTS


class RunnerTests(unittest.TestCase):
    def dispatch_fixture(self, root, version):
        """Real planner/processes over a tiny registry with no product owners."""
        self.init(root)
        (root/".gitignore").write_text("artifacts/\n__pycache__/\n")
        configuration = copy.deepcopy(load(ROOT))
        configuration[1]["modules"] = {}
        policy = configuration[0]
        policy["bootstrap_suites"] = ["a-first", "z-later"]
        policy["release_suites"] = ["a-first", "z-later"]
        policy["suites"] = {name: {"state": "ready", "timeout_seconds": 1, "commands": []}
                            for name in policy["bootstrap_suites"]}
        if version == 2:
            for name in LOGIC_INPUTS:
                destination = root/name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT/name, destination)
            (root/"harness").mkdir(exist_ok=True)
            (root/"harness/validation.toml").write_text('''schema_version = 1
engineering_prefixes = []
engineering_paths = []
system_prefixes = []
system_paths = []
[modules]
[components]
[pairs]
''')
        return configuration

    def marker(self, name):
        return ["{python}", "-c", "from pathlib import Path; "
                f"Path('artifacts/order').open('a').write({name!r}+'\\n'); print({name!r})"]

    def test_first_or_middle_failure_and_timeout_stop_all_later_dispatch(self):
        started = time.monotonic()
        for version in (1, 2):
            for scope in ("bootstrap", "change"):
                for first in (0, 1):
                    for failure in ("failed", "timeout"):
                        with self.subTest(version=version, scope=scope, first=first, failure=failure), \
                                tempfile.TemporaryDirectory() as temporary, \
                                patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
                            root = Path(temporary)
                            config = self.dispatch_fixture(root, version)
                            commands = [self.marker("prefix")]*first
                            code = "print('original failure', flush=True); " + (
                                "raise SystemExit(7)" if failure == "failed" else "import time; time.sleep(10)")
                            commands += [["{python}", "-c", code], self.marker("never-same-suite")]
                            config[0]["suites"]["a-first"]["commands"] = commands
                            config[0]["suites"]["z-later"]["commands"] = [self.marker("never-later-suite")]
                            report, path = check(root, scope, None, config, "auto" if version == 2 else None)
                            self.assertFalse(report["passed"])
                            self.assertEqual(report["schema_version"], version)
                            row, tail = report["results"][:2]
                            self.assertEqual(row["status"], "failed")
                            self.assertEqual(row["blocked_by"], {"suite": "a-first", "command_index": first, "status": failure})
                            self.assertEqual(row["commands"][-1]["status"], failure)
                            self.assertEqual(len(row["commands"]), first+1)
                            if failure == "failed":
                                self.assertEqual(row["commands"][-1]["returncode"], 7)
                            for result in row["commands"]:
                                log = root/result["log"]
                                self.assertTrue(log.exists())
                                self.assertEqual(hashlib.sha256(log.read_bytes()).hexdigest(), result["log_sha256"])
                            self.assertEqual(row["not_run"][0]["command_index"], first+1)
                            self.assertEqual(tail["status"], "blocked")
                            self.assertEqual(tail["blocked_by"], row["blocked_by"])
                            self.assertNotIn("commands", tail)
                            self.assertEqual(set(tail["not_run"][0]), {"command_index", "argv"})
                            marker = root/"artifacts/order"
                            self.assertEqual(marker.read_text().splitlines() if marker.exists() else [], ["prefix"]*first)
                            self.assertEqual(len(list(path.parent.glob("*.log"))), first+1)
                            if version == 2:
                                self.assertEqual(report["validation_cost"]["fresh_commands"], first+1)
                                self.assertEqual(report["validation_cost"]["maximum_command_seconds"], first+3)
        self.assertLess(time.monotonic()-started, 20)

    def test_missing_empty_and_release_precondition_never_launch_commands(self):
        for version in (1, 2):
            for scope, missing in (("bootstrap", "planned"), ("change", "planned"),
                                   ("bootstrap", "empty"), ("release", "runtime")):
                with self.subTest(version=version, scope=scope, missing=missing), \
                        tempfile.TemporaryDirectory() as temporary, \
                        patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
                    root = Path(temporary)
                    config = self.dispatch_fixture(root, version)
                    for suite in config[0]["suites"].values():
                        suite["commands"] = [self.marker("never")]
                    if missing != "runtime":
                        config[0]["suites"]["a-first"]["commands"] = []
                    if missing == "planned":
                        config[0]["suites"]["a-first"].update(state="planned", reason="original missing reason")
                    report, path = check(root, scope, None, config, "auto" if version == 2 else None)
                    self.assertFalse(report["passed"])
                    first, tail = report["results"][0], report["results"][-1]
                    self.assertEqual(first["status"], "missing")
                    self.assertEqual(tail["status"], "blocked")
                    self.assertEqual(tail["blocked_by"], {"suite": first["suite"], "status": "missing"})
                    self.assertFalse((root/"artifacts/order").exists())
                    self.assertEqual(list(path.parent.glob("*.log")), [])
                    if missing == "planned":
                        self.assertEqual(first["reason"], "original missing reason")
                        self.assertIn("a-first", report["unimplemented_suites"])
                    if version == 2:
                        self.assertEqual(report["validation_cost"]["fresh_commands"], 0)

    def test_success_keeps_every_command_order_argv_and_timeout(self):
        for version in (1, 2):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temporary, \
                    patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
                root = Path(temporary)
                config = self.dispatch_fixture(root, version)
                config[0]["suites"]["a-first"]["commands"] = [self.marker(x) for x in ("one", "two", "three")]
                config[0]["suites"]["z-later"]["commands"] = [self.marker("last")]
                with patch("harnesslib.runner.run_command", wraps=run_command) as execute:
                    report, _ = check(root, "bootstrap", None, config, "auto" if version == 2 else None)
                self.assertTrue(report["passed"])
                self.assertEqual((root/"artifacts/order").read_text().splitlines(), ["one", "two", "three", "last"])
                self.assertEqual([call.args[3] for call in execute.call_args_list], [1]*4)
                actual = [command["argv"] for row in report["results"] for command in row["commands"]]
                expected = [[sys.executable, *argv[1:]] for suite in config[0]["suites"].values() for argv in suite["commands"]]
                self.assertEqual(actual, expected)
                self.assertTrue(all("not_run" not in row for row in report["results"]))

    def test_missing_tool_and_output_limit_also_stop_dispatch(self):
        for version in (1, 2):
            for failure in ("missing_tool", "output_limit"):
                with self.subTest(version=version, failure=failure), tempfile.TemporaryDirectory() as temporary, \
                        patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
                    root = Path(temporary)
                    config = self.dispatch_fixture(root, version)
                    command = [str(root/"absent-tool")] if failure == "missing_tool" else [
                        "{python}", "-c", "print('x'*5000)"]
                    config[0]["suites"]["a-first"]["commands"] = [command]
                    config[0]["suites"]["z-later"]["commands"] = [self.marker("never")]
                    def bounded(argv, cwd, log, timeout):
                        return run_command(argv, cwd, log, timeout, max_log_bytes=256)
                    with patch("harnesslib.runner.run_command", side_effect=bounded):
                        report, _ = check(root, "bootstrap", None, config, "auto" if version == 2 else None)
                    self.assertFalse(report["passed"])
                    self.assertEqual(report["results"][0]["commands"][0]["status"], failure)
                    self.assertEqual(report["results"][1]["status"], "blocked")
                    self.assertFalse((root/"artifacts/order").exists())

    def configuration(self):
        configuration = copy.deepcopy(load(ROOT))
        configuration[0]["bootstrap_suites"] = ["smoke"]
        configuration[0]["suites"]["smoke"] = {
            "state": "ready", "timeout_seconds": 5,
            "commands": [["{python}", "-c", "print('fixture gate')"]]}
        return configuration

    def init(self, root):
        subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)

    def test_worktree_hook_environment_cannot_mutate_parent_git_state(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);outer=base/'outer';outer.mkdir()
            def command(root,*args):
                return subprocess.check_output(['git',*args],cwd=root)
            self.init(outer)
            command(outer,'config','user.name','Outer fixture')
            command(outer,'config','user.email','outer@example.invalid')
            (outer/'file').write_text('outer')
            command(outer,'add','file');command(outer,'commit','-m','outer')
            worktree=base/'worktree'
            command(outer,'worktree','add','-b','task',str(worktree))
            gitdir=Path(command(worktree,'rev-parse','--absolute-git-dir').decode().strip())
            before=(command(worktree,'rev-parse','HEAD'),(outer/'.git/config').read_bytes(),(gitdir/'index').read_bytes())
            script=("import pathlib,subprocess; p=pathlib.Path('nested');p.mkdir(); "
                    "subprocess.run(['git','init','-b','main'],cwd=p,check=True); "
                    "subprocess.run(['git','config','core.bare','false'],cwd=p,check=True); "
                    "subprocess.run(['git','config','user.name','Nested'],cwd=p,check=True); "
                    "(p/'nested.txt').write_text('nested');subprocess.run(['git','add','.'],cwd=p,check=True); "
                    "subprocess.run(['git','-c','user.email=nested@example.invalid','commit','-m','nested'],cwd=p,check=True)")
            with patch.dict(os.environ,{'GIT_DIR':str(gitdir),'GIT_COMMON_DIR':str(outer/'.git'),
                                        'GIT_INDEX_FILE':str(gitdir/'index'),'GIT_WORK_TREE':str(worktree),'GIT_PREFIX':''}):
                result=run_command([sys.executable,'-c',script],worktree,base/'hook.log',5)
            self.assertEqual(result['status'],'passed',(base/'hook.log').read_text())
            self.assertEqual(before,(command(worktree,'rev-parse','HEAD'),(outer/'.git/config').read_bytes(),(gitdir/'index').read_bytes()))
            self.assertTrue((worktree/'nested/.git/HEAD').is_file())

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
            planned = {"rust", "functional", "performance-smoke", "stability-component"}
            pending = {item["suite"] for item in report["results"] if item["status"] in {"missing", "blocked"}}
            self.assertTrue(planned.issubset(pending))
            self.assertEqual(sum(item["status"] == "missing" for item in report["results"]), 1)
            for item in report["results"]:
                if item["suite"] in planned and item["status"] == "blocked":
                    self.assertEqual(item["planned_state"], "planned")
                    self.assertEqual(item["planned_reason"], "fixture missing runtime")
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
