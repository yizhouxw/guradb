"""Exemptions stay exact, auditable and unable to mask unrelated missing lines."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from coverage_policy import read_lcov, summarize


class CoveragePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.name = 'crates/core/src/lib.rs'
        self.source = self.root/self.name
        self.source.parent.mkdir(parents=True)
        self.source.write_text('fn guard() {\n    return;\n}\n')
        self.files = {self.name: {1: 1, 2: 0, 3: 0}}
        self.item = {
            'path': self.name, 'source_sha256': hashlib.sha256(self.source.read_bytes()).hexdigest(),
            'category': 'library-invariant', 'reason': 'An upstream invariant prevents this fallback.',
            'evidence': 'tests/unit/guard.rs validates caller preconditions.',
            'lines': [{'number': 2, 'text': '    return;'}],
        }
        self.manifest = self.root/'exclusions.json'
        self.write([self.item])

    def write(self, items):
        self.manifest.write_text(json.dumps({'schema_version': 1, 'rust': items}))

    def test_raw_and_adjusted_counts_preserve_other_missing_lines(self):
        report = summarize(self.root, self.files, self.manifest)
        self.assertEqual(report['totals'], {'raw_lines': 3, 'raw_covered': 1,
            'excluded_lines': 1, 'excluded_covered': 0, 'eligible_lines': 2, 'eligible_covered': 1, 'missing_lines': 1})
        self.assertEqual(report['files'][self.name]['missing_lines'], [3])
        self.files[self.name][3] = 1
        self.assertEqual(summarize(self.root, self.files, self.manifest)['totals']['missing_lines'], 0)
        self.files[self.name][2] = 1
        report = summarize(self.root, self.files, self.manifest)
        self.assertEqual(report['totals']['excluded_covered'], 1)
        self.assertEqual(report['totals']['eligible_covered'], 2)

    def test_stale_source_requires_review_even_if_excluded_line_unchanged(self):
        self.source.write_text(self.source.read_text()+'// changed caller\n')
        with self.assertRaisesRegex(ValueError, 'stale'):
            summarize(self.root, self.files, self.manifest)

    def test_rejects_broad_stale_duplicate_and_undocumented_exclusions(self):
        variants = [
            {'path': 'crates/*/src/*.rs'}, {'category': 'everything'}, {'reason': ' '}, {'evidence': ''},
            {'lines': []}, {'lines': [{'number': 2, 'text': 'wrong'}]},
            {'lines': [{'number': True, 'text': 'fn guard() {'}]},
            {'lines': [{'number': 99, 'text': 'absent'}]},
            {'lines': [{'start': 1, 'end': 3}]},
            {'category': 'llvm-mapping'},
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                self.write([{**self.item, **changes}])
                with self.assertRaises(ValueError):
                    summarize(self.root, self.files, self.manifest)
        self.write([self.item, self.item])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            summarize(self.root, self.files, self.manifest)
        del self.item['evidence']
        self.write([self.item])
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            summarize(self.root, self.files, self.manifest)

    def test_rejects_whole_source_exclusion_and_noninteger_schema(self):
        self.item['lines'] = [{'number': n, 'text': text} for n, text in
                              enumerate(self.source.read_text().splitlines(), 1)]
        self.write([self.item])
        with self.assertRaisesRegex(ValueError, 'whole-source'):
            summarize(self.root, self.files, self.manifest)
        self.manifest.write_text(json.dumps({'schema_version': True, 'rust': []}))
        with self.assertRaisesRegex(ValueError, 'schema'):
            summarize(self.root, self.files, self.manifest)

    def test_lcov_uses_source_da_not_nested_function_lf_and_rejects_missing_sources(self):
        path = self.root/'rust.lcov'
        record = f'SF:/workspace/{self.name}\nDA:1,1\nDA:2,0\nDA:3,1\nLF:4\nLH:2\nend_of_record\n'
        path.write_text(record)
        self.assertEqual(read_lcov(path, {self.name}), {self.name: {1: 1, 2: 0, 3: 1}})
        for text, sources in [('', {self.name}), (record, {self.name, 'crates/other/src/lib.rs'}),
                (record*2, {self.name}), (record.replace('DA:2,0', 'DA:1,0'), {self.name}),
                (record.replace('DA:2,0', 'DA:2,-1'), {self.name}),
                (record, {'crates/other/src/lib.rs'}),
                (record.replace('DA:1,1\nDA:2,0\nDA:3,1\n', ''), {self.name})]:
            with self.subTest(text=text, sources=sources):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    read_lcov(path, sources)
