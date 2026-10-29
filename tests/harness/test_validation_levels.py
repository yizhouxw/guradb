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
from harnesslib.validation_registry import digest, load_registry, required_closure, source_inventory, validate_candidate


def candidate_fixture():
    contract = {"version": "read-control/1.0.0-rc2", "canonical_sha256":
                "da6a094b292dc382cfc48b305045753e67ed4bccf580dcafab81393db5d3d462"}
    methods = []
    for name, producer, consumers, path in (
            ("Read-Control", "common", ["catalog", "query", "gateway"], "crates/guradb-common/src/cf1a/missing_candidate_read_control.rs"),
            ("RC-B", "catalog", ["query"], "crates/guradb-catalog/src/read_control.rs"),
            ("Compiler", "query", ["gateway"], "crates/guradb-query/src/compile.rs")):
        methods.append({"id": name, "owner": producer, "consumers": consumers, "trigger_paths": [path],
                        "contract": dict(contract), "observations": ["O1", "O2", "O3", "O4"],
                        "driver_profile": {"id": name+"-fixture", "state": "pending", "reason": "real_driver_missing"}})
    return {"mode": "candidate", "contract": contract, "qa_source": "QA66-v0.1/6386816588 draft", "methods": methods}


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
        self.assertEqual(set(docs["suites"]), {"repository"})
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

    def test_unregistered_is_unresolved_and_preserves_production_selection(self):
        value = self.select(["crates/guradb-query/src/compile.rs"])["profile"]
        self.assertEqual(value["level"], "module")
        closure = value["required_closure"]
        self.assertEqual(closure["mode"], "unregistered")
        self.assertEqual(closure["unresolved"], [{"reason": "registry_not_connected"}])
        for key in ("contract", "methods", "required_owners", "required_consumers", "driver_profiles"):
            self.assertIsNone(closure[key])

    def test_candidate_propagates_all_explicit_consumers_with_pending_evidence(self):
        policy, architecture, invariants = self.configuration[:3]
        registry = copy.deepcopy(load_registry(ROOT, policy, architecture))
        registry["candidate_closure"] = candidate_fixture()
        common, catalog, query = [item["trigger_paths"][0] for item in registry["candidate_closure"]["methods"]]
        expected = [(common, ["catalog", "common", "gateway", "query"], ["Compiler", "RC-B", "Read-Control"]),
                    (catalog, ["catalog", "gateway", "query"], ["Compiler", "RC-B"]),
                    (query, ["gateway", "query"], ["Compiler"])]
        for path, owners, methods in expected:
            with self.subTest(path=path), patch("harnesslib.validation.load_registry", return_value=registry):
                selected = validation_plan(ROOT, [path], policy, architecture, invariants)
                profile = selected["profile"]
                closure = profile["required_closure"]
                self.assertEqual(profile["level"], "system")
                self.assertEqual(profile["modules"], [])
                self.assertEqual(closure["required_owners"], owners)
                self.assertEqual(closure["methods"], methods)
                self.assertIn("gateway", closure["required_consumers"])
                self.assertTrue(closure["unresolved"])
                self.assertEqual({row["state"] for row in closure["driver_profiles"]}, {"pending"})
                for level, requested in (("module", ["query"]), ("pair", ["query", "storage"])):
                    with self.assertRaisesRegex(HarnessError, "candidate pending"):
                        validation_plan(ROOT, [path], policy, architecture, invariants, level, requested)
        combined = required_closure([query, common, catalog], registry, architecture)
        reordered = required_closure([catalog, common, query], registry, architecture)
        self.assertEqual(combined, reordered)
        # Deleted/not-yet-created trigger paths remain meaningful inputs.
        self.assertFalse((ROOT/common).exists())
        self.assertEqual(required_closure([common], registry, architecture)["methods"], expected[0][2])
        unknown = required_closure([common, "crates/guradb-common/src/old_ports.rs"], registry, architecture)
        self.assertIsNone(unknown["required_consumers"])
        self.assertIsNone(unknown["methods"])
        self.assertEqual(unknown["unresolved"][-1]["reason"], "unmapped_trigger")
        empty = required_closure(["README.md"], registry, architecture)
        self.assertEqual(empty["methods"], [])  # Resolved no matching interface, unlike unknown input.
        self.assertEqual(empty["unresolved"], [])
        overlapping = copy.deepcopy(registry)
        finish = copy.deepcopy(overlapping["candidate_closure"]["methods"][1])
        finish["id"] = "RC-F"
        overlapping["candidate_closure"]["methods"].append(finish)
        self.assertEqual(required_closure([catalog], overlapping, architecture)["methods"],
                         ["Compiler", "RC-B", "RC-F"])

    def test_candidate_registry_rejects_unknown_conflicting_and_unqualified_data(self):
        policy, architecture = self.configuration[:2]
        changes = [lambda c: c.update(mode="active"), lambda c: c.update(extra=True),
                   lambda c: c["contract"].update(canonical_sha256="not-a-digest"),
                   lambda c: c["methods"].append(copy.deepcopy(c["methods"][0])),
                   lambda c: c["methods"][0].update(owner="unknown"),
                   lambda c: c["methods"][0].update(consumers=["unknown"]),
                   lambda c: c["methods"][0].update(consumers=["common"]),
                   lambda c: c["methods"][2].update(consumers=["storage"]),
                   lambda c: c["methods"][1]["contract"].update(version="different"),
                   lambda c: c["methods"][0].update(trigger_paths=["../escape.rs"]),
                   lambda c: c["methods"][0].update(trigger_paths=["crates/guradb-query/src/compile.rs"]),
                   lambda c: c["methods"][0].update(observations=[]),
                   lambda c: c["methods"][0]["driver_profile"].update(state="ready"),
                   lambda c: c["methods"][0]["driver_profile"].update(state=[])]
        for change in changes:
            candidate = candidate_fixture()
            change(candidate)
            registry = copy.deepcopy(load_registry(ROOT, policy, architecture))
            registry["candidate_closure"] = candidate
            with self.subTest(change=change), patch("harnesslib.validation_registry.read_toml", return_value=registry):
                with self.assertRaises(HarnessError):
                    load_registry(ROOT, policy, architecture)
        # Even a fixture architecture permitting reciprocal edges cannot hide a cycle.
        cyclic = copy.deepcopy(architecture)
        cyclic["modules"]["common"]["allowed"] = ["catalog"]
        candidate = candidate_fixture()
        candidate["methods"][1]["consumers"] = ["common"]
        with self.assertRaisesRegex(HarnessError, "cycle"):
            validate_candidate(candidate, cyclic)


if __name__ == "__main__":
    unittest.main()


class ThresholdPackageEntryTests(unittest.TestCase):
    def test_threshold_imports_from_both_supported_entry_roots(self):
        import subprocess
        import sys
        for root, module in ((ROOT, "scripts.harnesslib.runner"),
                             (ROOT / "scripts", "harnesslib.runner")):
            with self.subTest(module=module):
                code = ("import sys; sys.path.insert(0, " + repr(str(root)) + "); "
                        "import " + module + "; "
                        "from " + module.rsplit(".", 1)[0] + ".validation import THRESHOLDS; "
                        "assert THRESHOLDS == {'python': 80, 'rust': 100}")
                result = subprocess.run([sys.executable, "-I", "-c", code],
                                        cwd=ROOT, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
