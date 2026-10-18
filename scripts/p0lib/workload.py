"""Concurrent managed writes, refresh, retrieval and training on three workers."""
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

from m0lib.kit import DATASET, PG, laboratory, write
from m1lib.fixtures import pg, target
from m2lib.fixtures import Serving, edges, features, query, workers
from modules.catalog.managed import Managed
from modules.common.contracts import Budget, digest, key
from modules.connectors.writer import Writer
from modules.index.retrieval import load_bundle
from modules.query.incremental import refresh
from modules.query.snapshot import construct, publish
from p0lib.contract import (APPEND_ROWS, INITIAL_ROWS, canonical, document, environment,
                            input_vectors, population, query_pairs, sha, tree_bytes, workload_contract)
from p0lib.oracle import SourceOracle, assert_accepted_context
from p0lib.schedule import plan, stop_on_exit, validate_trace, wait_for_update


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def run(directory, duration=0, rounds=2, updates=2, transport="local"):
    directory = Path(directory).resolve()
    observations, update_trace, resource_samples = [], [], []
    stop = threading.Event()
    evidence_lock = threading.Lock()
    known = {}
    offsets = list(plan(duration, updates).scheduled_offsets)
    contract, inputs = workload_contract(duration, updates, offsets, transport)
    input_directory = directory/'inputs'
    input_directory.mkdir(parents=True)
    input_trace = {'contract': contract, 'inputs': inputs, 'views': []}
    write(input_directory/'trace.json', input_trace)

    def source_oracle(rows, feature, selected, built, previous=None):
        context = built['artifact']['context']
        assert context['read_view_id'] == 'view_'+str(built['id'])
        assert context['read_view_id'] not in known, 'append reused an existing read view'
        assert context['read_consistency'] == 'published'
        assert context['source_versions'] == [
            {'source_id': DATASET, 'format': 'iceberg-v2', 'version': str(selected['snapshot_id'])},
            {'source_id': DATASET+':metadata', 'format': 'iceberg-v2-metadata',
             'version': selected['metadata_sha256']},
            {'source_id': 'm2-test-17', 'format': 'features-v1', 'version': feature[1]}]
        source_features = json.loads(Path(feature[0].removeprefix('file://')).read_text())
        assert {r['logical_key']: r['vector'] for r in source_features['records']} == {
            key(i, 'long'): vector for i, vector in input_vectors(rows).items()}
        oracle = SourceOracle(rows, source_features, dataset_id=DATASET,
                              revision=context['data_revision_id'], read_context=context, previous=previous)
        input_trace['views'].append({'rows': list(rows), 'features': source_features, 'context': context})
        write(input_directory/'trace.json', input_trace)
        known[context['read_view_id']] = (oracle, len(rows))
        return oracle

    def guarded(function, *args):
        try:
            return function(*args)
        except BaseException:
            stop.set()
            raise

    with laboratory(directory) as lab:
        control, _, dsn = pg(lab)
        managed = Managed(dsn)
        managed.initialize()
        writer = Writer(directory/'lake', 'documents')
        writer.initialize(managed)
        rows = [document(i) for i in range(INITIAL_ROWS)]
        source = writer.append(managed, 'initial', rows)
        feature, vectors = features(writer.root, rows)
        selected = dict(source, features_uri=feature[0], features_sha256=feature[1], ann={'partitions': 4})
        control.register(DATASET, 'tenant-a', 'documents',
                         {'root': writer.root.as_uri(), 'key_field': 'id', 'text_field': 'title'})
        token = 'local-p0-integration'
        control.grant(digest(token.encode()), 'tenant-a', 'reader', DATASET)
        initial = construct(control, DATASET, 'initial', selected, directory/'builds')
        original = load_bundle(initial['artifact'], Budget())
        initial_oracle = source_oracle(rows, feature, selected, initial)
        initial_oracle.assert_materialized(original['rows'])
        publish(control, initial['id'], 0)
        graph_id = str(uuid.uuid4())
        table, edge_rows = edges(directory/'edges')
        edge_feature, _ = features(directory/'edges', edge_rows)
        control.register(graph_id, 'tenant-a', 'relations',
                         {'root': (directory/'edges').as_uri(), 'key_field': 'id', 'text_field': 'kind'})
        control.grant(digest(token.encode()), 'tenant-a', 'reader', graph_id)
        graph_run = construct(control, graph_id, 'initial', target(table, edge_feature), directory/'builds')
        graph_bundle = load_bundle(graph_run['artifact'], Budget())
        input_trace['graph_context'] = graph_bundle['context']
        write(input_directory/'trace.json', input_trace)
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
        pairs = query_pairs(vectors, DATASET, graph_id)

        def event(action, **values):
            with evidence_lock:
                lab.event(action, elapsed_seconds=time.monotonic()-start, **values)

        def background():
            assert begin_background.wait(10)
            current = list(rows)
            previous = initial_oracle
            for number, offset in enumerate(offsets):
                if not wait_for_update(start, offset, stop,
                                       interval=offsets[1]-offsets[0] if duration else None):
                    break
                began = time.monotonic()
                batch = [document(i) for i in range(len(current), len(current)+APPEND_ROWS)]
                operation = 'append-'+str(number)
                event('append_started', operation=operation, scheduled_seconds=offset,
                      rows_before=len(current), rows_added=len(batch))
                committed = writer.append(managed, operation, batch)
                committed_at = time.monotonic()-start
                assert writer.append(managed, operation, batch) == committed
                current.extend(batch)
                added_features, _ = features(writer.root, current)
                chosen = dict(committed, features_uri=added_features[0], features_sha256=added_features[1],
                              ann={'partitions': 4})
                built = refresh(control, DATASET, operation, chosen, directory/'builds')
                bundle = load_bundle(built['artifact'], Budget())
                previous = source_oracle(current, added_features, chosen, built, previous)
                previous.assert_materialized(bundle['rows'])
                epoch = publish(control, built['id'], number+1)
                published_at = time.monotonic()-start
                assert publish(control, built['id'], number+1) == epoch
                update_trace.append({'operation': operation, 'view': bundle['context']['read_view_id'],
                                     'rows': len(current), 'epoch': epoch, 'seconds': time.monotonic()-began,
                                     'scheduled_seconds': offset, 'started_seconds': began-start,
                                     'committed_seconds': committed_at, 'published_seconds': published_at,
                                     'build_stats': bundle['stats'], 'population': population(current),
                                     'retained_build_bytes': tree_bytes(directory/'builds'),
                                     'source_tree_bytes': tree_bytes(writer.root)})
                event('view_published', **update_trace[-1])
            return len(current)

        def request(kind, value, dataset=DATASET):
            before = time.monotonic()
            handle, result = query(serving.client, dataset, kind, value)
            try:
                # Preserve the observed payload before assertions, including a failing response.
                with evidence_lock:
                    with (directory/'responses.log').open('ab') as stream:
                        stream.write(canonical({'started_seconds':before-start, 'kind':kind, 'handle':handle,
                                                'query':value, 'result':result})+b'\n')
                assert_accepted_context(handle, result)
                if dataset == graph_id:
                    assert result['read_context'] == graph_bundle['context']
                    count = len(edge_rows)
                else:
                    oracle, count = known[handle['read_context']['read_view_id']]
                evidence = workers(result, count)
                assert all(0 < w['rss_bytes'] <= 512*(1 << 20) for w in evidence)
                if kind == 'scan':
                    oracle.assert_scan(result)
                elif kind == 'export':
                    oracle.assert_training(result, value)
                elif kind == 'graph':
                    # Relational truth independent of the graph implementation.
                    expected = [key(r['id'], 'long') for r in edge_rows if r['source'] in (0, 2) and r['kind'] == 'link']
                    assert [r['logical_key'] for r in result['paths']] == sorted(expected)
                else:
                    oracle.assert_search(result, value)
                observation = {'kind':kind, 'view':result['read_context']['read_view_id'],
                               'query_digest':sha(value), 'started_seconds':before-start,
                               'completed_seconds':time.monotonic()-start,
                               'latency_ms':(time.monotonic()-before)*1000, 'rows':count,
                               'workers':evidence, 'stats':result.get('stats', {}),
                               'coordinator_io_counters_available':'stats' in result,
                               'result_digest':sha(result),
                               'recall_at_10':1.0 if kind=='search' and 'vector' in value
                               and 'text' not in value and len(result['hits']) == 10 else None}
                assert observation['latency_ms'] <= 10000
                with evidence_lock:
                    observations.append(observation)
                    with (directory/'requests.log').open('ab') as stream:
                        stream.write(canonical({'observation':observation, 'query':value})+b'\n')
                return result
            finally:
                serving.client.request('DELETE', '/v1/jobs/'+handle['query_id']+'/retention')

        try:
            with ThreadPoolExecutor(3) as pool, stop_on_exit(stop):
                writer_future = pool.submit(guarded, background)
                begin_background.set()
                iteration = 0
                while iteration < rounds or time.monotonic()-start < duration:
                    for a, b in pairs:
                        left, right = pool.submit(guarded, request, *a), pool.submit(guarded, request, *b)
                        left.result()
                        right.result()
                        if writer_future.done():
                            writer_future.result()
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
                assert conn.execute('SELECT epoch FROM gura_m1.datasets WHERE id=%s',(DATASET,)).fetchone()['epoch'] == len(offsets)+1
            elapsed = time.monotonic()-start
            assert elapsed >= duration
            window = validate_trace(duration, update_trace, observations)
            lab.event('p0_concurrent_complete',iterations=iteration,updates=len(update_trace),requests=len(observations))
            return {'passed':True, 'scope':'local bounded three-worker concurrent integration', 'seed':17,
                    'environment':environment(Path(__file__).resolve().parents[2], PG),
                    'cache':'OS cache uncontrolled; no cold/over-capacity claim',
                    'contract':contract, 'window_validation':window,
                    'parameters':{'initial_rows':256,'append_rows':16,'updates':len(offsets),'duration_seconds':duration,
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
