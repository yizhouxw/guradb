"""Administrative auth publication is atomic and fenced before test requests."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from m0lib.pgwire import publish_auth


class AuthPublicationTests(unittest.TestCase):
    def test_complete_replacement_and_container_hash_before_read(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as directory:
            auth = Path(directory)/'auth.json'
            auth.write_text('old')
            principals = [{'principal_id': 'reader'}]
            lab = Mock(auth=auth, principals=principals, server='owned-test-container')
            observed = []
            def visible(*args):
                observed.append(json.loads(auth.read_bytes()))
                self.assertEqual(args[:3], ('exec', 'owned-test-container', 'python3'))
                return Mock(stdout=hashlib.sha256(auth.read_bytes()).hexdigest()+'\n')
            lab.wait.side_effect = lambda predicate, seconds: self.assertTrue(predicate())
            with patch('m0lib.pgwire.docker', side_effect=visible):
                publish_auth(lab)
                override = [{'principal_id': 'auditor'}]
                publish_auth(lab, override)
            self.assertEqual(observed, [{'principals': principals}, {'principals': override}])
            self.assertEqual(lab.principals, principals)
            self.assertFalse(auth.with_suffix('.next.json').exists())
