"""Offline input and output ownership tests; not model/semantic evidence."""
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('clip_preparation', ROOT/'scripts/prepare_clip_features.py')
clip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clip)


class ClipPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def write_queries(self, value):
        path = self.root/'queries.json'
        path.write_text(json.dumps(value))
        return path

    def test_only_encoder_input_fields_and_bounded_queries(self):
        row = {'id': 'q1', 'text': 'a kitchen'}
        valid = {'format_version': 1, 'queries': [row]}
        self.assertEqual(clip.queries(self.write_queries(valid)), [row])
        for bad in ({**valid, 'labels': []}, {**valid, 'format_version': True},
                    {**valid, 'queries': []}, {**valid, 'queries': [row]*9},
                    {**valid, 'queries': [row, row]},
                    {**valid, 'queries': [{**row, 'image_id': 397133}]},
                    {**valid, 'queries': [{**row, 'id': '../x'}]},
                    {**valid, 'queries': [{**row, 'text': 'snow '*9}]},
                    {**valid, 'queries': [{**row, 'text': '中文'}]},
                    {**valid, 'queries': [{**row, 'text': 'x'*65}]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                clip.queries(self.write_queries(bad))

    def test_duplicate_keys_and_byte_bound_reject(self):
        path = self.root/'bad.json'
        path.write_text('{"format_version":1,"format_version":1,"queries":[]}')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            clip.queries(path)
        path.write_bytes(b' ' * 65537)
        with self.assertRaisesRegex(ValueError, 'byte bound'):
            clip.queries(path)

    def test_existing_model_cache_is_never_touched_or_downloaded(self):
        path = self.root/'model'; path.mkdir(); marker = path/'keep'; marker.write_text('keep')
        with patch.object(clip.urllib.request, 'urlopen') as network:
            with self.assertRaisesRegex(ValueError, 'cache exists'):
                clip.download(path)
            network.assert_not_called()
        self.assertEqual(marker.read_text(), 'keep')

    def test_model_identity_failure_and_download_failure_clean_only_new(self):
        with self.assertRaisesRegex(ValueError, 'identity differs'):
            clip.validate_model(self.root)
        target = self.root/'new-cache'
        with patch.object(clip.urllib.request, 'urlopen', side_effect=ValueError('injected pre-payload failure')):
            with self.assertRaisesRegex(ValueError, 'injected'):
                clip.download(target)
        self.assertFalse(target.exists())
        self.assertTrue(self.root.exists())

    def test_existing_export_and_outside_output_reject_before_worker(self):
        path = self.root/'artifacts/existing'; path.mkdir(parents=True); marker = path/'keep'; marker.write_text('keep')
        with patch.object(clip, 'ROOT', self.root), patch.object(clip.subprocess, 'Popen') as spawn:
            for output in (Path('artifacts/existing'), Path('../outside'), self.root/'absolute'):
                with self.assertRaises((ValueError, FileExistsError)):
                    clip.export(self.root/'none', self.root/'model', self.root/'queries', output)
            spawn.assert_not_called()
        self.assertEqual(marker.read_text(), 'keep')

    def test_real_child_error_cleans_new_output_and_preserves_parent(self):
        # Current engineering interpreter has no model environment: actual child
        # must fail before ML, parent waits/exits and removes its owned output.
        with patch.object(clip, 'ROOT', self.root):
            with self.assertRaisesRegex(ValueError, 'offline export failed'):
                clip.export(self.root/'missing-config', self.root/'missing-model', self.root/'missing-query', Path('artifacts/failed'))
        self.assertFalse((self.root/'artifacts/failed').exists())
        self.assertTrue(self.root.exists())

    def test_real_parquet_media_contract_rejects_noncanonical_locator(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        payload = b'\xff\xd8\xfffixture-not-decoded'
        (self.root/'images').mkdir()
        (self.root/'images/000000000007.jpg').write_bytes(payload)
        row = {'doc_id': 'sample', 'text': 'metadata fixture only', 'text_version': 1,
               'image_id': 7, 'image_path': 'images/000000000007.jpg', 'media_version': 1,
               'media_bytes': len(payload), 'media_sha256': hashlib.sha256(payload).hexdigest()}
        schema = pa.schema([('doc_id', pa.string()), ('text', pa.string()), ('text_version', pa.int64()),
                            ('image_id', pa.int64()), ('image_path', pa.string()), ('media_version', pa.int64()),
                            ('media_bytes', pa.int64()), ('media_sha256', pa.string())])
        def write(locator):
            pq.write_table(pa.Table.from_pylist([{**row, 'image_path': locator}], schema=schema), self.root/'records.parquet')
            config = self.root/'config.json'
            config.write_text(json.dumps({'source': 'records.parquet', 'sha256': clip.digest(self.root/'records.parquet'), 'timeout_ms': 5000}))
            return config
        self.assertEqual(clip.corpus(write(row['image_path']))[2][0], row)
        for locator in ('images/7.jpg', 'images/000000000008.jpg', 'other/photo.jpg', '../photo.jpg', '/tmp/photo.jpg'):
            with self.subTest(locator=locator), self.assertRaisesRegex(ValueError, 'media-v1'):
                clip.corpus(write(locator))


if __name__ == '__main__':
    unittest.main()
