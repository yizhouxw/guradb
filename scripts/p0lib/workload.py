"""Concurrent managed writes, refresh, retrieval and training on three workers."""
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import threading
import time
import uuid

from m0lib.kit import DATASET, laboratory
from m1lib.fixtures import pg, target
from m2lib.fixtures import Serving, edges, features, query, workers
from modules.catalog.managed import Managed
from modules.common.contracts import Budget, digest, encoded, key
from modules.connectors.training import samples_for
from modules.connectors.writer import Writer
from modules.index.graph import expand
from modules.index.retrieval import load_bundle, search
from modules.query.incremental import refresh
from modules.query.snapshot import construct, publish


def document(i):
    return {'id': i, 'title': ['alpha alpha beta', 'beta', 'gamma database', 'database alpha'][i % 4],
            'active': i % 2 == 0}


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def run(directory, duration=0, rounds=2, updates=2, transport="local"):
    directory = Path(directory).resolve()
    observations, update_trace, resource_samples = [], [], []
    stop = threading.Event()
    known = {}
    with laboratory(directory) as lab:
        control, _, dsn = pg(lab)
        managed = Managed(dsn)
        managed.initialize()
        writer = Writer(directory/'lake', 'documents')
        writer.initialize(managed)
        rows = [document(i) for i in range(256)]
        source = writer.append(managed, 'initial', rows)
        feature, vectors = features(writer.root, rows)
        selected = dict(source, features_uri=feature[0], features_sha256=feature[1], ann={'partitions': 4})
        control.register(DATASET, 'tenant-a', 'documents',
                         {'root': writer.root.as_uri(), 'key_field': 'id', 'text_field': 'title'})
        token = 'local-p0-integration'
        control.grant(digest(token.encode()), 'tenant-a', 'reader', DATASET)
        initial = construct(control, DATASET, 'initial', selected, directory/'builds')
        original = load_bundle(initial['artifact'], Budget())
        known[original['context']['read_view_id']] = original
        publish(control, initial['id'], 0)
        graph_id = str(uuid.uuid4())
        table, edge_rows = edges(directory/'edges')
        edge_feature, _ = features(directory/'edges', edge_rows)
        control.register(graph_id, 'tenant-a', 'relations',
                         {'root': (directory/'edges').as_uri(), 'key_field': 'id', 'text_field': 'kind'})
        control.grant(digest(token.encode()), 'tenant-a', 'reader', graph_id)
        graph_run = construct(control, graph_id, 'initial', target(table, edge_feature), directory/'builds')
        graph_bundle = load_bundle(graph_run['artifact'], Budget())
        publish(control, graph_run['id'], 0)
        remote = None
        if transport == 'http':
            from p0lib.workers import RemoteWorkers
            remote = RemoteWorkers(directory/'workers', directory)
        serving = Serving(control, directory/'jobs', token,
                          worker_endpoints=remote.endpoints if remote else None,
                          worker_secret=remote.secret if remote else None)
        start = time.monotonic()
        begin_background = threading.Event()

        def background():
            assert begin_background.wait(10)
            current = list(rows)
            previous = original
            for number in range(updates):
                if stop.is_set():
                    break
                began = time.monotonic()
                batch = [document(i) for i in range(len(current), len(current)+16)]
                operation = 'append-'+str(number)
                committed = writer.append(managed, operation, batch)
                assert writer.append(managed, operation, batch) == committed
                current.extend(batch)
                added_features, _ = features(writer.root, current)
                chosen = dict(committed, features_uri=added_features[0], features_sha256=added_features[1],
                              ann={'partitions': 4})
                built = refresh(control, DATASET, operation, chosen, directory/'builds')
                bundle = load_bundle(built['artifact'], Budget())
                assert [r['values'] for r in sorted(bundle['rows'], key=lambda r:r['logical_key'])] == current
                old_versions = {r['logical_key']: r.get('record_version', previous['revision']) for r in previous['rows']}
                assert all(r.get('record_version', bundle['revision']) == old_versions[r['logical_key']]
                           for r in bundle['rows'] if r['logical_key'] in old_versions)
                previous = bundle
                known[bundle['context']['read_view_id']] = bundle
                epoch = publish(control, built['id'], number+1)
                assert publish(control, built['id'], number+1) == epoch
                update_trace.append({'operation': operation, 'view': bundle['context']['read_view_id'],
                                     'rows': len(current), 'epoch': epoch, 'seconds': time.monotonic()-began,
                                     'build_stats': bundle['stats']})
            return len(current)

        def request(kind, value, dataset=DATASET):
            before = time.monotonic()
            handle, result = query(serving.client, dataset, kind, value)
            try:
                bundle = graph_bundle if dataset == graph_id else known[result['read_context']['read_view_id']]
                assert result['read_context'] == bundle['context']
                evidence = workers(result, len(bundle['rows']))
                assert all(0 < w['rss_bytes'] <= 512*(1 << 20) for w in evidence)
                if kind == 'scan':
                    assert [r['logical_key'] for r in result['rows']] == sorted(r['logical_key'] for r in bundle['rows'])
                    versions = {r['logical_key']:r.get('record_version', bundle['revision']) for r in bundle['rows']}
                    assert all(r['record_version'] == versions[r['logical_key']] for r in result['rows'])
                elif kind == 'export':
                    assert result['samples'] == samples_for(bundle, value, Budget())
                elif kind == 'graph':
                    # Relational truth independent of the graph implementation.
                    expected = [key(r['id'], 'long') for r in edge_rows if r['source'] in (0, 2) and r['kind'] == 'link']
                    assert [r['logical_key'] for r in result['paths']] == sorted(expected)
                else:
                    exact_request = {k:v for k,v in value.items() if k not in ('vector_index', 'nprobes')}
                    oracle = search(bundle, exact_request, Budget())
                    assert result['hits'] == oracle['hits']
                    if 'vector' in value and 'text' not in value:
                        expected = sorted(bundle['rows'], key=lambda r:(math.fsum((a-b)**2 for a,b in zip(r['vector'],value['vector'])),r['logical_key']))[:10]
                        assert [h['logical_key'] for h in result['hits']] == [r['logical_key'] for r in expected]
                observation = {'kind':kind, 'view':result['read_context']['read_view_id'],
                               'latency_ms':(time.monotonic()-before)*1000, 'rows':len(bundle['rows']),
                               'workers':evidence, 'stats':result.get('stats', {}),
                               'recall_at_10':1.0 if kind=='search' and 'vector' in value else None}
                assert observation['latency_ms'] <= 10000
                observations.append(observation)
                return result
            finally:
                serving.client.request('DELETE', '/v1/jobs/'+handle['query_id']+'/retention')

        try:
            graph = {'source_field':'source', 'target_field':'target', 'type_field':'kind', 'seeds':['0','2'],
                     'type':'link', 'max_edges':100, 'max_fanout':100}
            vector = {'vector':vectors[19], 'model':'m2-test-17', 'top_k':10, 'candidate_limit':100}
            with ThreadPoolExecutor(3) as pool:
                writer_future = pool.submit(background)
                begin_background.set()
                iteration = 0
                while iteration < rounds or time.monotonic()-start < duration:
                    pairs = [
                        (('search', dict(vector, text='alpha'), DATASET), ('export', {'seed':'local-p0'}, DATASET)),
                        (('search', dict(vector, vector_index='ann', nprobes=4), DATASET), ('graph', graph, graph_id)),
                        (('search', {'text':'alpha beta', 'top_k':10, 'candidate_limit':100}, DATASET), ('scan', {'limit':1000}, DATASET))]
                    for a, b in pairs:
                        left, right = pool.submit(request, *a), pool.submit(request, *b)
                        left.result()
                        right.result()
                    rss = int(subprocess.check_output(['ps','-o','rss=','-p',str(os.getpid())],text=True).strip())*1024
                    assert rss <= 512*(1 << 20)
                    with control.transaction() as conn:
                        jobs = conn.execute('SELECT count(*) AS n FROM gura_m1.jobs').fetchone()['n']
                        pins = conn.execute("SELECT count(*) AS n FROM gura_m1.pins WHERE scope='job'").fetchone()['n']
                    assert jobs == pins == 0
                    resource_samples.append({'elapsed_seconds':time.monotonic()-start,'rss_bytes':rss,'jobs':jobs,'job_pins':pins})
                    iteration += 1
                final_rows = writer_future.result()
            # Clients exercise the same running service after concurrent publication.
            from tests.functional.mcp import run as mcp_run
            assert mcp_run(serving.client.url, token, DATASET)
            command = [os.sys.executable, str(Path(__file__).resolve().parents[2]/'clients/cli/m1.py'),
                       '--url', serving.client.url, 'scan', '--dataset', DATASET, '--query', '{"limit":1000}']
            cli = subprocess.run(command, env=dict(os.environ, GURADB_TOKEN=token), capture_output=True, text=True, check=True, timeout=15)
            assert len(json.loads(cli.stdout)['rows']) == final_rows
            with control.transaction() as conn:
                assert conn.execute('SELECT epoch FROM gura_m1.datasets WHERE id=%s',(DATASET,)).fetchone()['epoch'] == updates+1
            elapsed = time.monotonic()-start
            assert elapsed >= duration
            lab.event('p0_concurrent_complete',iterations=iteration,updates=len(update_trace),requests=len(observations))
            return {'passed':True, 'scope':'local bounded three-worker concurrent integration', 'seed':17,
                    'environment':platform.platform(), 'cache':'OS cache uncontrolled; no cold/over-capacity claim',
                    'parameters':{'initial_rows':256,'append_rows':16,'updates':updates,'duration_seconds':duration,
                                  'query_concurrency':2,'worker_count':3,'transport':transport,'top_k':10,'candidate_limit':100,'dimensions':16},
                    'elapsed_seconds':elapsed,'iterations':iteration,'requests':observations,'updates':update_trace,
                    'resource_samples':resource_samples,'latency_p95_ms':percentile([r['latency_ms'] for r in observations],.95),
                    'latency_p99_ms':percentile([r['latency_ms'] for r in observations],.99),'cli':True,'mcp':True,
                    'production_soak_passed':False}
        finally:
            stop.set()
            serving.close()
            if remote:
                remote.close()
