"""Owner denominator, exact LLVM inventory and unchanged reviewed exclusions."""
import json
import re
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from coverage_policy import read_lcov, summarize
from coverage_scope import coverage_scope, ignore_regex, package_args, production_sources
from harnesslib.policy import HarnessError


class CoverageScopeTests(unittest.TestCase):
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
