import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from harnesslib.policy import HarnessError, changed_paths, load, normalize_path, plan, validate_policy


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = load(ROOT)

    def test_existing_policy_is_valid(self):
        validate_policy(*self.config)

    def test_document_changes_do_not_claim_runtime_quality(self):
        result = plan(ROOT, ["docs/vision.md"], *self.config[:3])
        self.assertFalse(result["runtime_changed"])
        self.assertNotIn("performance", result["required_suites"])

    def test_storage_change_requires_component_quality_without_whole_engine(self):
        result = plan(ROOT, ["modules/storage/src/cache.rs"], *self.config[:3])
        self.assertTrue({"rust", "functional", "performance-smoke", "stability-component"}.issubset(result["required_suites"]))
        self.assertFalse({"performance", "stability", "soak"}.intersection(result["required_suites"]))
        self.assertIn("INV-006", result["invariants"])
        self.assertIn("query", result["impacted_modules"])
        self.assertIn("INV-001", result["invariants"])

    def test_shared_type_change_includes_downstream_client_obligations(self):
        result = plan(ROOT, ["modules/common/src/types.rs"], *self.config[:3])
        self.assertTrue({"query", "gateway", "cli", "mcp"}.issubset(result["impacted_modules"]))
        self.assertIn("INV-012", result["invariants"])

    def test_unknown_code_is_conservative(self):
        result = plan(ROOT, ["new_engine.py"], *self.config[:3])
        self.assertTrue({"functional", "performance-smoke", "stability-component"}.issubset(result["required_suites"]))

    def test_dependency_change_requires_runtime_gates(self):
        result = plan(ROOT, ["Cargo.lock"], *self.config[:3])
        self.assertIn("performance-smoke", result["required_suites"])
        self.assertIn("stability-component", result["required_suites"])

    def test_runtime_configuration_and_test_driver_changes_cannot_bypass_gates(self):
        for path, required in (
            ("modules/index/settings.toml", {"functional", "performance-smoke", "stability-component"}),
            ("config/query.yaml", {"functional", "performance-smoke", "stability-component"}),
            ("requirements-m1.lock", {"rust", "functional", "performance-smoke", "stability-component"}),
            ("scripts/m1.py", {"functional", "performance-smoke", "stability-component"}),
            ("scripts/m1_acceptance.py", {"functional", "performance-smoke", "stability-component"}),
            ("scripts/m1lib/fixtures.py", {"functional", "performance-smoke", "stability-component"}),
            ("requirements-m0.lock", {"rust", "functional", "performance-smoke", "stability-component"}),
            ("scripts/m0lib/kit.py", {"rust", "functional", "performance-smoke", "stability-component"}),
            ("scripts/m0.py", {"functional", "performance-smoke", "stability-component"}),
            ("deploy/Dockerfile", {"functional", "performance-smoke", "stability-component"}),
            ("tests/performance/driver.py", {"performance"}),
            ("tests/faults/driver.py", {"stability"}),
            ("tests/integration/test_query.py", {"functional"}),
        ):
            with self.subTest(path=path):
                result = plan(ROOT, [path], *self.config[:3])
                self.assertTrue(required.issubset(result["required_suites"]))

    def test_component_drivers_do_not_require_unimplemented_whole_engine(self):
        for path, suite in (
            ("tests/performance/component/scan.py", "performance-smoke"),
            ("benchmarks/component/scan.rs", "performance-smoke"),
            ("tests/faults/component/restart.py", "stability-component"),
        ):
            with self.subTest(path=path):
                result = plan(ROOT, [path], *self.config[:3])
                self.assertIn(suite, result["required_suites"])
                self.assertFalse({"performance", "stability", "soak"}.intersection(result["required_suites"]))

    def test_fixed_indexes_driver_changes_require_all_component_evidence(self):
        required = {"python", "functional", "performance-smoke", "stability-component", "unit-coverage"}
        for path in ("scripts/fixed_indexes_acceptance.py", "tests/index_support/__init__.py",
                     "tests/index_support/fixed_audit.py"):
            with self.subTest(path=path):
                result = plan(ROOT, [path], *self.config[:3])
                self.assertTrue(required.issubset(result["required_suites"]))
                self.assertFalse({"performance", "stability", "soak"}.intersection(result["required_suites"]))
        docs = plan(ROOT, ["tests/index_support/README.md"], *self.config[:3])
        self.assertFalse(required.intersection(docs["required_suites"]))

    def test_release_keeps_component_and_complete_engine_obligations(self):
        self.assertTrue({"performance-smoke", "stability-component", "performance", "stability", "soak"}
                        .issubset(self.config[0]["release_suites"]))

    def test_fixed_catalog_driver_changes_require_all_component_evidence(self):
        required = {"python", "functional", "performance-smoke", "stability-component", "unit-coverage"}
        for path in ("scripts/fixed_catalog_acceptance.py", "tests/catalog_support/__init__.py",
                     "tests/catalog_support/pg_transport.py"):
            with self.subTest(path=path):
                result = plan(ROOT, [path], *self.config[:3])
                self.assertTrue(required.issubset(result["required_suites"]))
                self.assertFalse({"performance", "stability", "soak"}.intersection(result["required_suites"]))
        docs = plan(ROOT, ["tests/catalog_support/README.md"], *self.config[:3])
        self.assertFalse(required.intersection(docs["required_suites"]))
    def test_fixed_object_driver_and_support_cannot_bypass_component_gates(self):
        required = {"python", "functional", "performance-smoke", "stability-component", "unit-coverage"}
        for path in ("scripts/fixed_objects_acceptance.py", "tests/storage_support/__init__.py",
                     "tests/storage_support/fixtures.py", "tests/storage_support/fault_server.py",
                     "tests/storage_support/recording_proxy.py", "tests/storage_support/acceptance.py",
                     "tests/storage_support/log_capture.py", "tests/storage_support/future_helper.py"):
            with self.subTest(path=path):
                result = plan(ROOT, [path], *self.config[:3])
                self.assertTrue(result["runtime_changed"])
                self.assertTrue(required.issubset(result["required_suites"]))
                self.assertFalse({"rust", "performance", "stability", "soak"}
                                 .intersection(result["required_suites"]))
        documentation = plan(ROOT, ["tests/storage_support/README.md"], *self.config[:3])
        self.assertFalse(documentation["runtime_changed"])
        self.assertEqual(set(documentation["required_suites"]), set(self.config[0]["bootstrap_suites"]))

    def test_fixed_source_driver_and_support_cannot_bypass_component_gates(self):
        required = {"python", "functional", "performance-smoke", "stability-component", "unit-coverage"}
        paths = ["scripts/fixed_sources_acceptance.py", "tests/source_support/__init__.py",
                 "tests/source_support/fixed_fixture.py", "tests/source_support/fixed_acceptance.py",
                 "tests/source_support/fixed_backend_cases.py", "tests/source_support/fixed_fault_cases.py",
                 "tests/source_support/fixed_evidence.py"]
        for path in paths:
            with self.subTest(path=path):
                result = plan(ROOT, [path], *self.config[:3])
                self.assertTrue(result["runtime_changed"])
                self.assertTrue(required.issubset(result["required_suites"]))
                self.assertFalse({"rust", "performance", "stability", "soak"}
                                 .intersection(result["required_suites"]))
        documentation = plan(ROOT, ["tests/source_support/README.md"], *self.config[:3])
        self.assertFalse(documentation["runtime_changed"])
        self.assertEqual(set(documentation["required_suites"]), set(self.config[0]["bootstrap_suites"]))

    def test_fixed_source_gates_execute_all_three_modes(self):
        suites = self.config[0]["suites"]
        for suite, mode in (("functional", "functional"), ("performance-smoke", "performance"),
                            ("stability-component", "fault")):
            commands = [command for command in suites[suite]["commands"]
                        if "scripts/fixed_sources_acceptance.py" in command]
            self.assertEqual(commands, [["{python}", "scripts/fixed_sources_acceptance.py", "--mode", mode,
                                         "--run-dir", "{run_dir}/fixed-sources-" + mode]])
        compileall = suites["python"]["commands"][0]
        self.assertIn("scripts/fixed_sources_acceptance.py", compileall)
        self.assertIn("tests/source_support", compileall)

    def test_client_cannot_hide_as_documentation(self):
        result = plan(ROOT, ["clients/cli/main.py"], *self.config[:3])
        self.assertIn("functional", result["required_suites"])

    def test_invalid_ready_suite_and_invariant_are_rejected(self):
        for mutate in (
            lambda config: config[0]["suites"]["functional"].update(state="ready", commands=[]),
            lambda config: config[2]["invariants"][0].update(suite="missing-suite"),
            lambda config: config[4]["scenarios"][0].update(invariants=["INV-999"]),
        ):
            config = copy.deepcopy(self.config)
            mutate(config)
            with self.assertRaises(HarnessError):
                validate_policy(*config)

    def test_paths_cannot_escape_repository(self):
        for value in ("../secret.rs", "/tmp/file", "a/../../b"):
            with self.assertRaises(HarnessError):
                normalize_path(value)

    def test_changes_include_untracked_and_both_sides_of_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            git("init", "-b", "main")
            (root / "old.rs").write_text("old\n")
            git("add", ".")
            git("-c", "user.name=Harness Test", "-c", "user.email=harness@example.invalid", "commit", "-m", "fixture")
            git("mv", "old.rs", "renamed.rs")
            (root / "untracked.rs").write_text("new\n")
            self.assertEqual(changed_paths(root, None), ["old.rs", "renamed.rs", "untracked.rs"])
            with self.assertRaises(HarnessError):
                changed_paths(root, "missing-reference")


if __name__ == "__main__":
    unittest.main()
