"""Owner denominator, exact LLVM inventory and unchanged reviewed exclusions."""
import json
import re
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from coverage_policy import read_lcov, summarize
from coverage_scope import coverage_scope, ignore_regex, package_args, production_sources
from harnesslib.policy import HarnessError
from harnesslib.policy import load
from harnesslib.validation_registry import load_registry, validate_candidate


class CoverageScopeTests(unittest.TestCase):
    def test_candidate_metadata_never_narrows_source_inventory_or_waives_a_language(self):
        config = load(ROOT)
        registry = load_registry(ROOT, *config[:2])
        # coverage_scope must ignore candidate execution claims and retain its original rules.
        contract = {"version": "fixture-contract", "canonical_sha256": "a"*64}
        registry["candidate_closure"] = {"mode": "candidate", "contract": contract, "qa_source": "fixture",
            "methods": [{"id": "Compiler", "contract": contract, "owner": "query", "consumers": ["gateway"],
                         "trigger_paths": ["crates/guradb-query/src/lib.rs"], "observations": ["O1"],
                         "driver_profile": {"id": "fixture", "state": "pending", "reason": "driver_missing"}}]}
        validate_candidate(registry["candidate_closure"], config[1])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            subprocess.run(["git", "init", "-b", "main"], cwd=root, capture_output=True, check=True)
            first = root/"modules/query/unimported.py"
            first.parent.mkdir(parents=True)
            first.write_text("VALUE = 1\n")
            rust = root/"crates/guradb-query/src/lib.rs"
            rust.parent.mkdir(parents=True)
            rust.write_text("pub fn value() {}\n")
            subprocess.run(["git", "add", "."], cwd=root, capture_output=True, check=True)
            with patch("coverage_scope.load", return_value=config), patch("coverage_scope.load_registry", return_value=registry):
                self.assertIn("modules/query/unimported.py", coverage_scope(root, ["query"])["python_sources"])
                renamed = first.with_name("renamed.py")
                first.rename(renamed)
                actual = coverage_scope(root, ["query"])
                self.assertEqual(actual["python_sources"], ["modules/query/renamed.py"])
                self.assertEqual(actual["rust_sources"], ["crates/guradb-query/src/lib.rs"])
                self.assertEqual(actual["threshold_percent"], {"python": 80, "rust": 100})
                (root/".gitignore").write_text("renamed.py\n")
                with self.assertRaisesRegex(HarnessError, "ignored runtime source"):
                    coverage_scope(root, ["query"])
                (root/".gitignore").unlink()
                renamed.unlink()
                with self.assertRaisesRegex(HarnessError, "both owner languages"):
                    coverage_scope(root, ["query"])

    def test_scope_keeps_never_imported_owner_sources_and_only_selected_packages(self):
        scope = coverage_scope(ROOT, ["query"])
        self.assertIn("modules/query/remote_worker.py", scope["python_sources"])
        self.assertIn("crates/guradb-query/src/sql.rs", scope["rust_sources"])
        self.assertEqual(scope["threshold_percent"], {"python": 80, "rust": 100})
        self.assertEqual(scope["python_tests"], ["tests/contracts", "tests/unit"])
        self.assertEqual(package_args(scope), ["--package", "guradb-query"])
        self.assertEqual(package_args(None), ["--workspace"])
        self.assertIsNotNone(re.search(ignore_regex(ROOT, scope), "/workspace/crates/guradb-storage/src/lib.rs"))
        self.assertIsNone(re.search(ignore_regex(ROOT, scope), "/workspace/crates/guradb-query/src/lib.rs"))
        self.assertTrue(set(scope["sources"]).issubset(production_sources(ROOT)))
        pair = coverage_scope(ROOT, ["storage", "query"])
        self.assertIn("crates/guradb-storage/src/lib.rs", pair["rust_sources"])
        self.assertEqual(package_args(pair), ["--package", "guradb-query", "--package", "guradb-storage"])

    def test_unknown_duplicate_pending_and_empty_module_requests_reject(self):
        for modules in ([], ["not-an-owner"], ["query", "query"], ["catalog"]):
            with self.subTest(modules=modules), self.assertRaises(HarnessError):
                coverage_scope(ROOT, modules)

    def test_missing_or_extra_llvm_source_fails_instead_of_reducing_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"coverage.lcov"
            first = "crates/guradb-query/src/compile.rs"
            second = "crates/guradb-query/src/sql.rs"
            path.write_text(f"SF:/workspace/{first}\nDA:1,1\nend_of_record\n")
            with self.assertRaisesRegex(ValueError, "missing/empty"):
                read_lcov(path, {first, second})
            with self.assertRaisesRegex(ValueError, "unexpected coverage source"):
                read_lcov(path, {second})

    def test_scoped_summary_validates_every_existing_exemption_but_applies_only_owner(self):
        scope = coverage_scope(ROOT, ["query"])
        # Count fixture verifies scope/exemption algebra, not real line coverage.
        lines = {name: {number: 1 for number, _ in enumerate((ROOT/name).read_text().splitlines(), 1)}
                 for name in scope["rust_sources"]}
        universe = {name for name in production_sources(ROOT) if name.endswith(".rs")}
        manifest = ROOT/"harness/coverage-exclusions.json"
        value = summarize(ROOT, lines, manifest, universe=universe)
        self.assertEqual(set(value["files"]), set(scope["rust_sources"]))
        self.assertEqual(value["totals"]["missing_lines"], 0)
        raw = json.loads(manifest.read_text())
        expected = sum(len(item["lines"]) for item in raw["rust"] if item["path"] in lines)
        self.assertEqual(value["totals"]["excluded_lines"], expected)
        outside = next(item for item in raw["rust"] if item["path"] not in lines)
        outside["source_sha256"] = "0"*64
        with tempfile.TemporaryDirectory() as temporary:
            stale = Path(temporary)/"stale.json"
            stale.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError, "stale coverage exclusion"):
                summarize(ROOT, lines, stale, universe=universe)


if __name__ == "__main__":
    unittest.main()
