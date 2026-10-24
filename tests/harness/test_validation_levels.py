"""Risk selection tests use real mappings, without invoking component runtimes."""
import copy
import subprocess
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from harnesslib.policy import HarnessError, load
from harnesslib.validation import validation_plan
from harnesslib.validation_registry import digest, load_registry, source_inventory


class ValidationLevelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.configuration = load(ROOT)

    def select(self, paths, **options):
        return validation_plan(ROOT, paths, *self.configuration[:3], **options)

    def test_rust_owner_keeps_full_python_and_rust_denominator(self):
        value = self.select(["crates/guradb-query/src/compile.rs"])
        profile = value["profile"]
        self.assertEqual(profile["level"], "module")
        self.assertEqual(profile["modules"], ["query"])
        self.assertIn("modules/query/worker.py", profile["source_closure"])
        self.assertIn("crates/guradb-query/src/sql.rs", profile["source_closure"])
        self.assertNotIn("crates/guradb-query/tests/unit/compiler.rs", profile["source_closure"])
        self.assertNotIn("crates/guradb-storage/src/lib.rs", profile["source_closure"])
        self.assertEqual(profile["denominator"]["threshold_percent"], {"python": 80, "rust": 100})
        self.assertEqual(value["profile_sha256"], digest(profile))

    def test_pair_is_actual_registered_boundary_with_original_component_cost(self):
        value = self.select(["crates/guradb-storage/src/lib.rs", "crates/guradb-query/src/sql.rs"])
        profile = value["profile"]
        self.assertEqual(profile["level"], "pair")
        self.assertEqual(profile["pairs"], ["storage-query"])
        self.assertIn("not CF1-A/I1", profile["components"]["legacy-m0"]["boundary"])
        for part, suite in (("functional", "functional"), ("performance", "performance-smoke"),
                            ("fault", "stability-component")):
            actual = profile["suites"]["component-" + part]
            original = self.configuration[0]["suites"][suite]
            self.assertEqual(actual["commands"], [original["commands"][0]])
            self.assertEqual(actual["timeout_seconds"], original["timeout_seconds"])

    def test_delete_rename_both_sides_and_unknown_or_shared_cannot_downgrade(self):
        for paths in (["crates/guradb-query/src/deleted.rs", "crates/guradb-index/src/new.rs"],
                      ["unowned/engine.rs"], ["Cargo.lock"], ["api/cf1a/schema.json"],
                      ["modules/common/cf1a_wire.py"]):
            with self.subTest(paths=paths):
                value = self.select(paths)
                self.assertEqual(value["profile"]["level"], "system")
                self.assertTrue(value["selection_reasons"])
                with self.assertRaises(HarnessError):
                    self.select(paths, level="module", modules=["query"])

    def test_unmapped_python_explains_fallback_pending_never_invented_ready(self):
        for path, text in (("modules/query/service.py", "not mapped"),
                           ("modules/catalog/control.py", "unregistered")):
            value = self.select([path])
            self.assertEqual(value["profile"]["level"], "system")
            self.assertIn(text, " ".join(value["selection_reasons"]))

    def test_engineering_and_documentation_have_distinct_quality_claims(self):
        engineering = self.select(["scripts/harnesslib/runner.py"])["profile"]
        docs = self.select(["docs/user/fixed-query.md"])["profile"]
        self.assertEqual(engineering["level"], "engineering")
        self.assertIn("engineering-native", engineering["suites"])
        self.assertEqual(engineering["denominator"], {"rule": "not-production-coverage"})
        self.assertEqual(docs["level"], "documentation")
        self.assertEqual(set(docs["suites"]), set(self.configuration[0]["bootstrap_suites"]))
        mixed = self.select(["scripts/harnesslib/runner.py", "crates/guradb-query/src/lib.rs"])
        self.assertEqual(mixed["profile"]["level"], "system")

    def test_explicit_pair_can_expand_never_omit_owner_or_claim_unknown_pair(self):
        path = ["crates/guradb-query/src/lib.rs"]
        self.assertEqual(self.select(path, level="pair", modules=["query", "storage"])["profile"]["level"], "pair")
        for options in ({"level": "module", "modules": ["storage"]},
                        {"level": "pair", "modules": ["query"]},
                        {"level": "auto", "modules": ["query"]},
                        {"level": "module", "modules": ["query", "query"]}):
            with self.subTest(options=options), self.assertRaises(HarnessError):
                self.select(path, **options)

    def test_release_keeps_every_planned_obligation_and_system_all_ready(self):
        policy = self.configuration[0]
        system = self.select(["README.md"], level="system")["profile"]
        release = self.select(["README.md"], level="release")["profile"]
        self.assertEqual(set(system["suites"]), {name for name, suite in policy["suites"].items()
                                                if suite["state"] == "ready"})
        self.assertEqual(set(release["suites"]), set(policy["release_suites"]))
        self.assertEqual(release["suites"]["soak"]["state"], "planned")
        self.assertEqual(release["suites"]["soak"]["commands"], [])

    def test_required_planned_full_drivers_are_never_dropped_by_system_fallback(self):
        for path, gate in (("tests/soak/new_case.py", "soak"),
                           ("tests/performance/full_workload.py", "performance"),
                           ("tests/faults/full_registry.py", "stability")):
            with self.subTest(path=path):
                value = self.select([path])["profile"]
                self.assertEqual(value["level"], "system")
                self.assertEqual(value["suites"][gate]["state"], "planned")

    def test_owner_inventory_includes_nested_build_and_external_runtime_rust(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            paths = {"modules/query/entry.py": "from .build import worker\n",
                     "modules/query/build/worker.py": "VALUE = 1\n",
                     "crates/guradb-query/src/lib.rs": '#[path = "../runtime/worker.rs"]\nmod worker;\n',
                     "crates/guradb-query/runtime/worker.rs": "pub fn value() {}\n",
                     "crates/guradb-query/tests/unit/test.rs": "fn fixture() {}\n"}
            for path, text in paths.items():
                target = root/path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            actual = source_inventory(root, *self.configuration[:2], ["query"])
            self.assertEqual(set(actual), set(paths)-{"crates/guradb-query/tests/unit/test.rs"})
            # A new untracked owned file also counts; deleting a tracked source
            # removes its denominator while its old/new path still selects risk.
            (root/"modules/query/new.py").write_text("NEW = 1\n")
            (root/"modules/query/entry.py").unlink()
            actual = source_inventory(root, *self.configuration[:2], ["query"])
            self.assertIn("modules/query/new.py", actual)
            self.assertNotIn("modules/query/entry.py", actual)
            (root/"crates/guradb-query/src/lib.rs").write_text('#[path = "../../../outside.rs"]\nmod outside;\n')
            with self.assertRaisesRegex(HarnessError, "outside inventoried"):
                source_inventory(root, *self.configuration[:2], ["query"])

    def test_cargo_custom_target_cannot_escape_inventory_or_relabel_test_as_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            base = root/"crates/guradb-query"
            (base/"src").mkdir(parents=True)
            (base/"src/lib.rs").write_text("pub fn value() {}\n")
            (base/"Cargo.toml").write_text('[package]\nname="guradb-query"\n[lib]\npath="../../outside.rs"\n')
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            with self.assertRaisesRegex(HarnessError, "Cargo runtime target outside"):
                source_inventory(root, *self.configuration[:2], ["query"])

    def test_unmapped_production_language_is_rejected_instead_of_excluded_from_strict_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            target = root/"modules/query/plugin.go"
            target.parent.mkdir(parents=True)
            target.write_text("package query\n")
            with self.assertRaisesRegex(HarnessError, "no certified scope"):
                source_inventory(root, *self.configuration[:2], ["query"])

    def test_ignored_owned_runtime_source_fails_closed_instead_of_shrinking_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            (root/".gitignore").write_text("build/\n")
            target = root/"modules/query/build/worker.py"
            target.parent.mkdir(parents=True)
            target.write_text("VALUE = 1\n")
            with self.assertRaisesRegex(HarnessError, "ignored runtime source"):
                source_inventory(root, *self.configuration[:2], ["query"])

    def test_registry_rejects_missing_real_fault_command_and_unknown_owner(self):
        policy, architecture = copy.deepcopy(self.configuration[:2])
        policy["suites"]["stability-component"].update(state="planned", commands=[], reason="not ready")
        with self.assertRaises(HarnessError):
            load_registry(ROOT, policy, architecture)
        policy, architecture = copy.deepcopy(self.configuration[:2])
        architecture["modules"]["new-owner"] = {"paths": ["new/"], "allowed": []}
        with self.assertRaises(HarnessError):
            load_registry(ROOT, policy, architecture)


if __name__ == "__main__":
    unittest.main()
