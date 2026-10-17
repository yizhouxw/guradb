"""Real PG lost-index rebuild with offline facts, ANN/training truth and GC independence."""
import json
from pathlib import Path
import shutil
from unittest.mock import patch

from m0lib.kit import DATASET, laboratory
from m1lib.fixtures import iceberg, pg, target
from m2lib.fixtures import features
from modules.common.contracts import Budget, Failure, digest, encoded
from modules.connectors.training import samples_for
from modules.index.retrieval import load_bundle, search
from modules.query.rebuild import rebuild
from modules.query.snapshot import collect, construct, publish
from modules.storage.objects import get


def run(directory):
    directory = Path(directory).resolve()
    with laboratory(directory) as lab:
        control, _, _ = pg(lab)
        lake = directory/'lake'
        table, _, rows = iceberg(lake, 256)
        feature, vectors = features(lake, rows)
        media_path = lake/'media.bin'
        media_raw = b'immutable media bytes'
        media_path.write_bytes(media_raw)
        feature_path = Path(feature[0].removeprefix('file://'))
        value = json.loads(feature_path.read_bytes())
        value['records'][0]['media'] = [{'uri': media_path.as_uri(), 'sha256': digest(media_raw), 'size_bytes': len(media_raw)}]
        feature_path.write_bytes(encoded(value))
        feature = (feature[0], digest(feature_path.read_bytes()))
        control.register(DATASET, 'tenant', 'documents',
                         {'root': lake.as_uri(), 'key_field': 'id', 'text_field': 'title'})
        first = construct(control, DATASET, 'initial', dict(target(table, feature), ann={'partitions': 4}), directory/'builds')
        publish(control, first['id'], 0)
        old = load_bundle(first['artifact'], Budget())
        request = {'vector': vectors[19], 'model': 'm2-test-17', 'top_k': 10, 'candidate_limit': 100}
        expected = search(old, request, Budget())['hits']
        text = search(old, {'text': 'alpha beta'}, Budget())['hits']
        training = samples_for(old, {'seed': 'rebuild'}, Budget())
        control.pin(first['id'], 'training-kept')
        # Remove every derived index plus the unavailable external source.
        for path in ('tantivy', 'bm25', 'lance', 'shards'):
            shutil.rmtree(directory/'builds'/str(first['id'])/path)
        shutil.rmtree(lake)
        try:
            load_bundle(first['artifact'], Budget())
        except (Failure, OSError):
            pass
        else:
            raise AssertionError('old read silently ignored missing index')
        with patch('modules.storage.objects.Objects.read', side_effect=AssertionError('external source was fetched')):
            built = rebuild(control, DATASET, 'restore-indexes', directory/'builds')
        assert built['status'] == 'ready'
        assert control.dataset(DATASET)['published'] == first['id']
        assert rebuild(control, DATASET, 'restore-indexes', directory/'builds')['id'] == built['id']
        actual = load_bundle(built['artifact'], Budget())
        assert actual['revision'] == old['revision']
        assert actual['context']['data_revision_id'] == old['context']['data_revision_id']
        assert actual['context']['source_versions'] == old['context']['source_versions']
        assert actual['context']['read_view_id'] != old['context']['read_view_id']
        assert search(actual, request, Budget())['hits'] == expected
        assert search(actual, dict(request, vector_index='ann', nprobes=4), Budget())['hits'] == expected
        assert search(actual, {'text': 'alpha beta'}, Budget())['hits'] == text
        assert samples_for(actual, {'seed': 'rebuild'}, Budget()) == training
        try:
            publish(control, built['id'], 0)
        except Failure as error:
            assert error.code == 'publication_conflict'
        else:
            raise AssertionError('wrong epoch published rebuilt view')
        assert publish(control, built['id'], 1) == 2
        assert rebuild(control, DATASET, 'restore-indexes', directory/'builds')['id'] == built['id']
        with control.transaction() as conn:
            assert conn.execute('SELECT 1 FROM gura_m1.pins WHERE owner=%s', ('training-kept',)).fetchone()
        control.unpin(first['id'], 'training-kept')
        collect(control, first['id'], directory/'builds')
        independent = load_bundle(built['artifact'], Budget())
        assert len(independent['rows']) == 256
        assert get(independent['rows'][0]['media'][0]['copy']) == media_raw
        # Fact corruption is never excused by the index recovery path.
        dependency = actual['source']['dependencies'][0]['copy']
        preserved = Path(dependency['path']).read_bytes()
        Path(dependency['path']).write_bytes(b'corrupt fact')
        try:
            rebuild(control, DATASET, 'corrupt-facts', directory/'builds')
        except Failure as error:
            assert error.code == 'source_invalid', error.code
        else:
            raise AssertionError('corrupted immutable fact was accepted')
        failed = rebuild(control, DATASET, 'corrupt-facts', directory/'builds')
        assert failed['status'] == 'failed' and failed['artifact'] is None
        assert control.dataset(DATASET)['published'] == built['id']
        Path(dependency['path']).write_bytes(preserved)
        Path(dependency['path']).unlink()
        try:
            rebuild(control, DATASET, 'missing-facts', directory/'builds')
        except Failure as error:
            assert error.code == 'source_unavailable', error.code
        else:
            raise AssertionError('missing immutable fact was accepted')
        try:
            rebuild(control, DATASET, 'initial', directory/'builds')
        except Failure as error:
            assert error.code == 'operation_conflict'
        else:
            raise AssertionError('operation type collision was accepted')
        return {'passed': True, 'scope': 'local offline immutable fact index recovery',
                'truth': ['real PG replay/CAS/pins', 'exact and all-probe ANN', 'same-version training', 'fact corruption rejection'],
                'source_reads': 0}
