"""Real CLI/process/log receipts with tool fixtures, never database evidence."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from harnesslib.check_evidence import validate_report
from harnesslib.policy import HarnessError, load
from harnesslib.runner import check, checkout_digest
from harnesslib.validation_binding import LOGIC_INPUTS
from harnesslib.validation_registry import digest
from harnesslib.workflow import finish_task, start_task


class ValidationReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()/"repo"
        self.root.mkdir()
        environment = patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Validation tool fixture")
        self.git("config", "user.email", "validation@example.invalid")
        for pattern in ("scripts/harnesslib/*.py", "harness/*.toml"):
            for source in ROOT.glob(pattern):
                self.copy(source.relative_to(ROOT).as_posix())
        for source in LOGIC_INPUTS:
            self.copy(source)
        policy, architecture, *_ = load(ROOT)
        for name, module in architecture["modules"].items():
            # Each owner exists, but these are intentionally tiny source fixtures.
            prefix = module["paths"][0]
            target = self.root/prefix/"fixture.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("VALUE = 1\n")
        for package in ("guradb-query", "guradb-storage"):
            self.copy(f"crates/{package}/Cargo.toml")
            target = self.root/f"crates/{package}/src/lib.rs"
            target.parent.mkdir(parents=True)
            target.write_text("pub fn value() {}\n")
        for path in ("tests/contracts", "tests/unit"):
            (self.root/path).mkdir(parents=True)
        self.copy("scripts/harness.py")
        self.write("scripts/cargo.py", "import sys; print('tool fixture', sys.argv[1:])\n")
        self.write("scripts/unit_coverage.py", "print('coverage tool fixture; no product claim')\n")
        self.write(".gitignore", "artifacts/\n__pycache__/\n")
        # Persist the tiny argv fixtures so the real CLI sees the same policy.
        current_suite = None
        lines = []
        for line in (self.root/"harness/policy.toml").read_text().splitlines():
            if line.startswith("[suites."):
                current_suite = line[len("[suites."):-1]
            if line.startswith("commands =") and current_suite and policy["suites"][current_suite]["state"] == "ready":
                line = "commands = " + json.dumps([["{python}", "-c", "print('component tool fixture')"]])
            lines.append(line)
        self.write("harness/policy.toml", "\n".join(lines)+"\n")
        self.git("add", ".")
        self.git("commit", "-m", "fixture baseline")
        self.config = copy.deepcopy(load(self.root))
        for suite in self.config[0]["suites"].values():
            if suite["state"] == "ready":
                suite["commands"] = [["{python}", "-c", "print('component tool fixture')"]]
        self.started = start_task(self.root, "validation", "tool protocol fixture only", self.config)
        self.write("crates/guradb-query/src/lib.rs", "pub fn value() { let _ = 1; }\n")
        self.git("add", ".")
        self.git("commit", "-m", "fixture change")

    def copy(self, name):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, path)

    def write(self, name, data):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.DEVNULL).decode().strip()

    def report(self):
        report, path = check(self.root, "change", "auto", self.config, "auto", batch="fixture-batch")
        self.assertTrue(report["passed"])
        return report, path

    def test_module_completion_and_checkpoint_keep_claim_and_original_base(self):
        report, path = self.report()
        self.assertEqual(validate_report(self.root, path, self.config), report)
        completed = finish_task(self.root, path, "tool fixtures only, not product gates", self.config)
        self.assertEqual(completed["base_commit"], self.started["base_commit"])
        self.assertEqual(completed["validation"]["level"], "module")
        self.assertEqual(completed["validation"]["modules"], ["query"])
        tag = self.git("for-each-ref", "--format=%(contents)", "refs/tags/"+completed["final_checkpoint"])
        metadata = json.loads(tag)
        self.assertEqual(metadata["validation"], completed["validation"])
        self.assertEqual(metadata["validation"]["batch"], "fixture-batch")

    def test_forged_level_argv_hash_denominator_and_quality_claim_are_rejected(self):
        report, path = self.report()
        def level(value):
            value["validation"]["profile"]["level"] = "system"
            value["validation"]["profile_sha256"] = digest(value["validation"]["profile"])
        mutations = [level,
                     lambda v: v["results"].reverse(),
                     lambda v: v.update(level="release"),
                     lambda v: v["validation_cost"].update(reused_commands=1),
                     lambda v: v.update(product_quality="system_passed"),
                     lambda v: v["validation"].update(profile_sha256="0"*64),
                     lambda v: v["validation"]["profile"]["source_closure"].clear(),
                     lambda v: v["validation"]["profile"]["suites"]["module-rust"].update(timeout_seconds=1),
                     lambda v: v["results"][0]["commands"][0].update(argv=["true"])]
        for mutate in mutations:
            value = copy.deepcopy(report)
            mutate(value)
            path.write_text(json.dumps(value))
            with self.subTest(mutate=mutate), self.assertRaises(HarnessError):
                validate_report(self.root, path, self.config)

    def test_serial_wall_rejects_impossible_cost_but_allows_rounding_tolerance(self):
        report, path = self.report()
        commands = [command for result in report["results"] for command in result["commands"]]
        serial = sum(command["duration_seconds"] for command in commands)
        for impossible in (0, serial/2):
            value = copy.deepcopy(report)
            value["validation_cost"]["wall_seconds"] = impossible
            path.write_text(json.dumps(value))
            with self.subTest(wall=impossible), self.assertRaisesRegex(HarnessError, "cost counters"):
                validate_report(self.root, path, self.config)
        # Each command is rounded independently to milliseconds. A small total
        # rounding discrepancy must not reject an otherwise complete receipt.
        value = copy.deepcopy(report)
        value["validation_cost"]["wall_seconds"] = serial - len(commands)*0.0009
        path.write_text(json.dumps(value))
        self.assertEqual(validate_report(self.root, path, self.config), value)

    def test_changed_logic_or_command_input_cannot_reuse_profile_even_with_new_checkout_digest(self):
        logic = self.root/"scripts/harnesslib/validation.py"
        self.write("scripts/harnesslib/validation.py", logic.read_text()+"\n# first version\n")
        report, path = self.report()
        self.write("scripts/harnesslib/validation.py", (self.root/"scripts/harnesslib/validation.py").read_text()+"\n# changed logic\n")
        report["checkout_digest"] = checkout_digest(self.root, self.config[0])
        path.write_text(json.dumps(report))
        with self.assertRaisesRegex(HarnessError, "profile/source denominator"):
            validate_report(self.root, path, self.config)

    def test_additional_harness_helper_is_in_logic_closure_without_manual_whitelist_update(self):
        helper = "scripts/harnesslib/private_logic.py"
        self.assertNotIn(helper, LOGIC_INPUTS)
        self.write(helper, "VALUE = 1\n")
        report, path = self.report()
        self.assertIn(helper, report["validation"]["profile"]["selection_execution_logic"])
        self.write(helper, "VALUE = 2\n")
        report["checkout_digest"] = checkout_digest(self.root, self.config[0])
        path.write_text(json.dumps(report))
        with self.assertRaisesRegex(HarnessError, "profile/source denominator"):
            validate_report(self.root, path, self.config)

    def test_v2_system_fallback_executes_no_planned_driver_and_cannot_pass(self):
        self.write("tests/soak/new_case.py", "# full soak obligation, no certified driver\n")
        self.config[0]["suites"]["soak"]["commands"] = [["must-never-execute-planned"]]
        report, _ = check(self.root, "change", "auto", self.config, "auto")
        self.assertFalse(report["passed"])
        self.assertEqual(report["validation"]["profile"]["level"], "system")
        row = next(item for item in report["results"] if item["suite"] == "soak")
        self.assertEqual(row["status"], "missing")
        self.assertNotIn("commands", row)
        self.assertTrue(all("must-never-execute-planned" not in item["argv"]
                            for result in report["results"] for item in result.get("commands", [])))

    def test_running_change_to_nested_build_source_is_detected_by_profile_guard(self):
        self.write("modules/query/build/worker.py", "VALUE = 1\n")
        self.git("add", "modules/query/build/worker.py")
        self.git("commit", "-m", "owned nested source")
        self.config[0]["suites"]["repository"]["commands"] = [["{python}", "-c",
            "from pathlib import Path; Path('modules/query/build/worker.py').write_text('VALUE = 2\\n')"]]
        report, _ = check(self.root, "change", "auto", self.config, "auto")
        self.assertFalse(report["passed"])
        self.assertIn("validation-unchanged", {row["suite"] for row in report["results"]})

    def test_v1_retains_legacy_semantics_and_cannot_add_v2_claim(self):
        report, path = check(self.root, "change", "auto", self.config)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(validate_report(self.root, path, self.config), report)
        report["validation"] = {"profile": {"level": "system"}}
        path.write_text(json.dumps(report))
        with self.assertRaisesRegex(HarnessError, "legacy report"):
            validate_report(self.root, path, self.config)

    def test_real_cli_plan_and_downgrade_refusal_runs_no_quality_command(self):
        argv = [sys.executable, "scripts/harness.py", "plan", "--path", "crates/guradb-query/src/lib.rs"]
        result = subprocess.run(argv, cwd=self.root, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        planned = json.loads(result.stdout)["validation"]
        self.assertEqual(planned["profile"]["level"], "module")
        self.assertIn("selection_execution_logic", planned["profile"])
        result = subprocess.run([sys.executable, "scripts/harness.py", "check", "--level", "module",
                                 "--module", "storage", "--base", self.started["base_commit"]],
                                cwd=self.root, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("omit required validation closure", result.stderr)
        self.assertFalse((self.root/"artifacts/harness").exists())
        result = subprocess.run([sys.executable, "scripts/harness.py", "check", "--level", "module",
                                 "--module", "query", "--base", self.started["base_commit"], "--batch", "cli-fixture"],
                                cwd=self.root, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        reports = list((self.root/"artifacts/harness").glob("*/report.json"))
        self.assertEqual(len(reports), 1)
        report = validate_report(self.root, reports[0], self.config)
        self.assertEqual(report["validation"]["profile"]["level"], "module")
        self.assertEqual(report["batch"], "cli-fixture")


if __name__ == "__main__":
    unittest.main()
