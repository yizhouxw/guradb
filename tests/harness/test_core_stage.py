"""Stage protocol and negative evidence fixtures; never product acceptance."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"scripts"))
sys.path.insert(0, str(ROOT/"tests/harness"))
from harnesslib.check_evidence import validate_report
from harnesslib.policy import HarnessError, load
from harnesslib.runner import check, checkout_digest
from harnesslib.stages import CORE_PACKAGES, SELFTESTS, set_task_stage
from harnesslib import core_rust
from harnesslib.task_state import read_task
from harnesslib.validation import validation_plan
from harnesslib.validation_binding import bound_plan
from harnesslib.version_control import checkpoint, install_hooks
from harnesslib.workflow import abandon_task, finish_task, start_task
import test_validation_reports as report_fixtures


class CoreStageTests(unittest.TestCase):
    copy = report_fixtures.ValidationReportTests.copy
    write = report_fixtures.ValidationReportTests.write
    git = report_fixtures.ValidationReportTests.git

    def setUp(self):
        report_fixtures.ValidationReportTests.setUp(self)
        # Tiny commands/files are honest tool fixtures, not real HTTP/Rust.
        self.write("scripts/harnesslib/core_rust.py", "print('rustfmt tool fixture')\n")
        self.write("scripts/fixed_read_core_acceptance.py", "print('HTTP driver tool fixture')\n")
        for pattern in SELFTESTS:
            self.write("tests/harness/"+pattern.replace("*", "_fixture"),
                       "import unittest\nclass ToolFixture(unittest.TestCase):\n def test_protocol(self): pass\n")
        (self.root/".githooks/pre-commit").chmod(0o755)
        self.git("add", ".")
        self.git("commit", "-m", "bounded stage tool fixtures")
        abandon_task(self.root, "fixture preparation ended; retain original toy receipt")
        self.started = start_task(self.root, "bounded-core", "stage protocol fixture only", self.config,
                                  "core", "fixed-read")
        self.write("crates/guradb-query/src/lib.rs", "pub fn value() { let _ = 3; }\n")
        self.git("add", ".")
        self.git("commit", "-m", "core source tool fixture")

    def report(self):
        result, path = check(self.root, "change", "auto", self.config, "auto")
        self.assertTrue(result["passed"], result["results"])
        self.assertEqual(result["validation"]["profile"]["level"], "core-limited")
        return result, path

    def test_core_keeps_real_entry_command_rust_checks_source_binding_and_limits(self):
        selected = bound_plan(self.root, ["crates/guradb-query/src/lib.rs"], *self.config[:3])
        profile = selected["profile"]
        self.assertEqual((selected["stage"], selected["core_flow"]), ("core", "fixed-read"))
        self.assertEqual(set(profile["suites"]), {"repository", "policy", "contracts", "core-harness", "core-rust", "core-fixed-read"})
        commands = profile["suites"]["core-rust"]["commands"]
        self.assertEqual(commands[0], ["{python}", "scripts/harnesslib/core_rust.py", "crates/guradb-query/src/lib.rs"])
        for command, verb in zip(commands[1:], ("clippy", "test")):
            self.assertEqual(command[:3], ["{python}", "scripts/cargo.py", verb])
            self.assertIn("--locked", command)
            for package in CORE_PACKAGES:
                self.assertIn(package, command)
        self.assertEqual(profile["suites"]["core-fixed-read"]["commands"], [["{python}",
            "scripts/fixed_read_core_acceptance.py", "--run-dir", "{run_dir}/fixed-read-core"]])
        self.assertNotIn("threshold_percent", profile["denominator"])
        self.assertIn("crates/guradb-query/src/lib.rs", profile["source_closure"])
        self.assertIn("scripts/fixed_read_core_acceptance.py", profile["command_inputs"])
        self.assertIn("release not assessed", profile["limitations"])

    def test_documentation_only_never_launches_product_or_contract_suite(self):
        for stage, flow in (("hardening", None), ("core", "fixed-read")):
            selected = validation_plan(ROOT, ["harness/team-collaboration.md"], *load(ROOT)[:3],
                                       stage=stage, core_flow=flow)
            self.assertEqual(selected["profile"]["level"], "documentation")
            self.assertEqual(list(selected["profile"]["suites"]), ["repository"])
        # Machine policies and API contracts are never prose.
        selected = validation_plan(ROOT, ["api/http/openapi.json"], *load(ROOT)[:3])
        self.assertEqual(selected["profile"]["level"], "system")
        self.write("README.md", "# Prose tool fixture\n")
        report, _ = check(self.root, "change", "HEAD", self.config, "auto")
        self.assertTrue(report["passed"])
        self.assertEqual([row["suite"] for row in report["results"]], ["repository"])

    def test_core_unknown_scope_or_missing_stage_inputs_fail_closed(self):
        for options in ({"stage": "core"}, {"stage": "hardening", "core_flow": "fixed-read"},
                        {"stage": "core", "core_flow": "other"},
                        {"stage": "core", "core_flow": "fixed-read", "scope": "release"},
                        {"stage": "core", "core_flow": "fixed-read", "level": "system"}):
            with self.subTest(options=options), self.assertRaises(HarnessError):
                validation_plan(self.root, ["crates/guradb-query/src/lib.rs"], *self.config[:3], **options)
        for path in ("crates/guradb-index/src/lib.rs", "Cargo.lock", "modules/query/worker.py", "tests/soak/a.py"):
            with self.subTest(path=path), self.assertRaisesRegex(HarnessError, "unmapped"):
                bound_plan(self.root, [path], *self.config[:3])
        (self.root/"tests/harness/test_core_stage.py").unlink()
        with self.assertRaisesRegex(HarnessError, "selftest input missing"):
            bound_plan(self.root, ["crates/guradb-query/src/lib.rs"], *self.config[:3])

    def test_normal_hook_then_post_commit_finish_and_checkpoint_keep_core_claim(self):
        (self.root/".githooks/pre-commit").chmod(0o755)
        install_hooks(self.root)
        self.write("crates/guradb-query/src/lib.rs", "pub fn value() { let _ = 2; }\n")
        self.git("add", ".")
        result = subprocess.run(["git", "commit", "-m", "normal staged core fixture"], cwd=self.root,
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn("core-limited", result.stdout+result.stderr)
        report, path = self.report()
        self.assertEqual(validate_report(self.root, path, self.config), report)
        done = finish_task(self.root, path, "tool fixtures only; real HTTP/Rust not assessed", self.config)
        self.assertEqual(done["base_commit"], self.started["base_commit"])
        self.assertEqual(done["validation"]["level"], "core-limited")
        self.assertEqual(done["validation"]["stage"], "core")
        tag = self.git("for-each-ref", "--format=%(contents)", "refs/tags/"+done["final_checkpoint"])
        self.assertEqual(json.loads(tag)["validation"]["core_flow"], "fixed-read")
        # A post-merge checkout without an active receipt must explicitly carry
        # the same bounded scope, rather than silently claiming system quality.
        report, path = check(self.root, "change", self.started["base_commit"], self.config, "auto",
                              stage="core", core_flow="fixed-read")
        self.assertEqual(validate_report(self.root, path, self.config), report)
        self.assertEqual(report["product_quality"], "only_core-limited_profile")

    def test_failure_missing_driver_or_log_never_completes(self):
        driver = self.root/"scripts/fixed_read_core_acceptance.py"
        for source in (None, "print('original driver failure'); raise SystemExit(7)\n"):
            if source is None:
                driver.unlink()
            else:
                driver.write_text(source)
            report, path = check(self.root, "change", "auto", self.config, "auto")
            self.assertFalse(report["passed"])
            failed = next(row for row in report["results"] if row["suite"] == "core-fixed-read")
            self.assertEqual(failed["status"], "failed")
            with self.assertRaises(HarnessError):
                finish_task(self.root, path, "failed core must reject", self.config)
        driver.write_text("print('tool fixture')\n")
        self.git("add", ".")
        self.git("commit", "-m", "restore tool fixture")
        report, path = self.report()
        (self.root/report["results"][-1]["commands"][0]["log"]).unlink()
        with self.assertRaises(HarnessError):
            validate_report(self.root, path, self.config)
        with self.assertRaises(HarnessError):
            checkpoint(self.root, "missing-log", self.config[0], path, self.config)

    def test_source_logic_driver_or_test_change_invalidates_old_evidence(self):
        for name in ("crates/guradb-query/src/lib.rs", "scripts/harnesslib/stages.py",
                     "scripts/fixed_read_core_acceptance.py", "tests/harness/test_core_stage.py"):
            original = (self.root/name).read_text()
            report, path = self.report()
            self.write(name, original+"\n# changed evidence input\n")
            # Even refreshing the outer checkout digest cannot adopt old evidence.
            report["checkout_digest"] = checkout_digest(self.root, self.config[0])
            path.write_text(json.dumps(report))
            with self.subTest(name=name), self.assertRaises(HarnessError):
                validate_report(self.root, path, self.config)
            self.write(name, original)

    def test_hardening_and_release_do_not_inherit_core_exemptions(self):
        set_task_stage(self.root, "hardening")
        self.assertEqual(read_task(self.root)["base_commit"], self.started["base_commit"])
        for level in ("system", "release"):
            profile = bound_plan(self.root, ["README.md"], *self.config[:3], level=level)["profile"]
            self.assertIn("unit-coverage", profile["suites"])
            self.assertIn("performance-smoke", profile["suites"])
            if level == "release":
                self.assertEqual(profile["suites"]["soak"]["state"], "planned")

    def test_cli_task_stage_keeps_base_and_receipt_drift_cannot_finish(self):
        report, path = self.report()
        result = subprocess.run([sys.executable, "scripts/harness.py", "task-stage", "--stage", "hardening"],
                                cwd=self.root, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["base_commit"], self.started["base_commit"])
        with self.assertRaisesRegex(HarnessError, "stage must match"):
            finish_task(self.root, path, "do not promote core evidence", self.config)


class CoreRustCommandTests(unittest.TestCase):
    def test_changed_files_use_existing_pinned_toolchain_without_children(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root/"crates/demo/src/lib.rs"
            path.parent.mkdir(parents=True)
            path.write_text("pub fn bounded() {}\n")
            with patch.object(core_rust, "ROOT", root), patch.object(core_rust.subprocess, "run",
                    return_value=SimpleNamespace(returncode=5)) as execute:
                self.assertEqual(core_rust.main(["crates/demo/src/lib.rs"]), 5)
                build, check_fmt = [call.args[0] for call in execute.call_args_list]
                self.assertIn("tools/m0/Dockerfile", build)
                self.assertEqual(check_fmt[-7:], ["rustfmt", "--edition", "2021", "--check", "--config",
                                                 "skip_children=true", "crates/demo/src/lib.rs"])
                self.assertIn(core_rust.IMAGE, check_fmt)
                for invalid in ([], ["../outside.rs"], ["crates/missing.rs"], ["README.md"]):
                    with self.assertRaises(ValueError):
                        core_rust.main(invalid)
                self.assertEqual(execute.call_count, 2)


if __name__ == "__main__":
    unittest.main()
