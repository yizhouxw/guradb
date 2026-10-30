"""Bounded user tutorial over explicit, existing small input bundles; no downloads."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT/'docs/user/m1-inputs.json'
RUNTIME = 'sha256:09bc0a87408c56bd4fe912df3ba3d499ea2279ea32cdeddf051a7a3dd3ddb52f'
SQL = 'SELECT doc_id,text FROM records ORDER BY doc_id'
THREAD_ENV = dict(OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4', MKL_NUM_THREADS='4')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def checked_work(path):
    original = path.absolute()
    if '..' in original.parts or any(part.is_symlink() for part in (original, *original.parents)):
        raise ValueError('WORK must not contain symlinks or parent traversal')
    result = original.resolve()
    result.relative_to(ROOT/'artifacts')
    return result


def bounded(path, root, limit=8 << 20):
    path = Path(path)
    if not path.is_absolute():
        path = root/path
    path.relative_to(root)
    if '..' in path.parts or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('input path/size is outside the supported bound')
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('links are not supported inputs: '+str(path))
        if part == root:
            break
    with path.open('rb') as stream:
        raw = stream.read(limit+1)
    if len(raw) > limit:
        raise ValueError('input exceeds bound')
    return raw


def prepare(inputs, work, package):
    """Validate all declared small bytes before creating a fresh owned directory."""
    work = checked_work(work)
    inputs = inputs.resolve(strict=True)
    manifest = read_json(MANIFEST)
    if package.is_symlink() or not package.is_file() or package.stat().st_size > 1 << 30 or sha(package.read_bytes()) != manifest['preview_artifact_sha256']:
        raise ValueError('preview artifact SHA mismatch')
    payload = {}
    text_bytes = bounded(manifest['queries_text'], inputs)
    model_bytes = bounded(manifest['model_manifest'], inputs, 1 << 20)
    if sha(text_bytes) != manifest['queries_text_sha256'] or sha(model_bytes) != manifest['model_manifest_sha256']:
        raise ValueError('frozen query text/model provenance SHA mismatch')
    queries = json.loads(text_bytes)['queries']
    lineage = []
    for version in manifest['versions']:
        name = version['name']
        corpus = Path(version['corpus'])
        cfg = json.loads(bounded(corpus/'config.json', inputs))
        raw = bounded(corpus/cfg['source'], inputs, 32 << 20)
        if sha(raw) != cfg['sha256'] or cfg['sha256'] != version['source_sha256']:
            raise ValueError('source SHA mismatch')
        payload[name+'/records.parquet'] = raw
        cfg['source'] = 'records.parquet'
        payload[name+'/config.json'] = (json.dumps(cfg)+'\n').encode()
        features = bounded(version['features'], inputs)
        if sha(features) != version['features_sha256']:
            raise ValueError('feature SHA mismatch')
        payload[name+'/features.jsonl'] = features
        lines = [json.loads(line) for line in features.splitlines()]
        docs = sorted(row['doc_id'] for row in lines[1:])
        payload[name+'/selection.json'] = json.dumps(dict(format_version=1,
            source_sha256=cfg['sha256'], seed=0, doc_ids=docs)).encode()
        for image in manifest['images']:
            payload[name+'/'+image] = bounded(corpus/image, inputs, 512 << 10)
        for query in queries:
            original = bounded(Path(manifest['queries_dir'])/(query['id']+'.json'), inputs, 64 << 10)
            if sha(original) != manifest['query_files_sha256'][query['id']]:
                raise ValueError('frozen original query SHA mismatch')
            value = json.loads(original)
            value['source_sha256'] = cfg['sha256']
            encoded = (json.dumps(value, allow_nan=False)+'\n').encode()
            payload[name+'/queries/'+query['id']+'.json'] = encoded
            lineage.append(dict(version=name, query=query['id'], original_sha256=sha(original),
                                target_sha256=sha(encoded), vector_and_space_unchanged=True,
                                action='caller target binding only; no model execution'))
    if work.exists() or work.is_symlink():
        raise ValueError('fresh work directory required; refusing overwrite')
    work.parent.mkdir(parents=True, exist_ok=True)
    work.mkdir()
    try:
        (work/'data').mkdir()
        for relative, raw in payload.items():
            target = work/'data'/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        save(work/'inputs.json', dict(manifest=manifest, queries=queries, lineage=lineage,
             copied_input_bytes=sum(map(len, payload.values())), package=str(package.resolve()),
             provenance=dict(queries_text_sha256=sha(text_bytes), model_manifest_sha256=sha(model_bytes))))
    except BaseException:
        shutil.rmtree(work)
        raise


class Installed:
    def __init__(self, work):
        self.work = work.resolve()
        self.entry = self.work/'prefix/bin/guradb'
        self.data = self.work/'data'
        self.env = dict(os.environ, HOME=str(self.work/'home'), **THREAD_ENV)
        self.env.pop('PYTHONPATH', None)
        self.calls = []

    def process(self, command, timeout=35):
        start = time.perf_counter()
        p = subprocess.run([str(x) for x in command], env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        self.calls.append(dict(command=[str(x) for x in command], returncode=p.returncode,
            elapsed_s=time.perf_counter()-start, stdout_bytes=len(p.stdout), stderr_bytes=len(p.stderr)))
        if p.returncode or len(p.stdout) > 2 << 20:
            save(self.work/'last-failed-call.json', self.calls[-1])
            (self.work/'last-failed-call.stderr').write_bytes(p.stderr[:65536])
            raise RuntimeError('command failed: '+p.stderr[-2000:].decode('utf8', 'replace'))
        return json.loads(p.stdout)

    def call(self, *args):
        return self.process([self.entry, '--data-root', self.data, *args])

    def view(self, mode, view, *args):
        return self.call('view', mode, '--store', '/data/store', '--view', view, *args)

    def publish(self, name):
        version = next(v for v in read_json(self.work/'inputs.json')['manifest']['versions'] if v['name'] == name)
        prepared = self.call('view', 'prepare', '--store', '/data/store', '--config',
            '/data/'+name+'/config.json', '--request-id', 'tutorial-'+name,
            '--features', '/data/'+name+'/features.jsonl', '--features-sha256', version['features_sha256'])
        published = self.call('view', 'publish', '--store', '/data/store', '--request-id', 'tutorial-'+name)
        if prepared['view_id'] != published['view_id']:
            raise ValueError('publication identity mismatch')
        return published['view_id']


def media_summary(value):
    row = value['result'] if 'result' in value else value
    raw = bytes.fromhex(row['bytes_hex'])
    if len(raw) != row['media_bytes'] or sha(raw) != row['media_sha256']:
        raise ValueError('returned media bytes mismatch')
    return {key: item for key, item in row.items() if key != 'bytes_hex'}


async def sdk_flow(work, keyword):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    installed = Installed(work)
    views = read_json(work/'views.json')
    timings = []
    async def invoke(session, name, arguments):
        start = time.perf_counter()
        result = await session.call_tool(name, arguments)
        if result.isError:
            raise RuntimeError(str(result))
        timings.append(dict(tool=name, view=arguments['view'], elapsed_s=time.perf_counter()-start))
        return json.loads(result.content[0].text)
    async with stdio_client(StdioServerParameters(command=str(installed.entry),
        args=['--data-root', str(installed.data), 'mcp', '--store', '/data/store'], env=installed.env)) as streams:
        async with ClientSession(*streams) as session:
            initialization = await session.initialize()
            discovery = await session.list_tools()
            search = await invoke(session, 'guradb_search', dict(view=views['A'], query=keyword))
            hit = search['result']['hits'][0]
            evidence = await invoke(session, 'guradb_media', dict(view=search['view_id'], asset_id=int(hit['media']['asset_id'])))
            checked = media_summary(evidence)
            cli = media_summary(installed.view('media', views['A'], '--asset-id', hit['media']['asset_id']))
            if cli != checked:
                raise ValueError('SDK and independent CLI media differ')
            views['B'] = installed.publish('B')
            save(work/'views.json', views)
            current = await invoke(session, 'guradb_query', dict(view='current', sql=SQL))
            reused_search = await invoke(session, 'guradb_search', dict(view=views['A'], query=keyword))
            if reused_search != search:
                raise ValueError('same query on old fixed view changed after refresh')
            old = await invoke(session, 'guradb_media', dict(view=views['A'], asset_id=int(hit['media']['asset_id'])))
            if media_summary(old) != checked or current['view_id'] != views['B']:
                raise ValueError('refresh changed the pinned old view')
            return dict(protocol=initialization.protocolVersion, tools=[t.name for t in discovery.tools],
                        hit=dict(doc_id=hit['doc_id'], view_id=search['view_id'], media=checked),
                        current_view=current['view_id'], old_view_retained=True, cli_calls=installed.calls,
                        repeated_bm25=dict(query=keyword, hits=search['result']['hits'], count=2), timings=timings)


def tutorial(work, sdk_python, framework_python, keyword):
    installed = Installed(work)
    state = read_json(work/'inputs.json')
    (work/'home').mkdir(exist_ok=True)
    installed.process(['/usr/bin/python3', state['package'], 'install', '--sha256', state['manifest']['preview_artifact_sha256'], '--prefix', work/'prefix'], 75)
    doctor = installed.process([installed.entry, 'doctor'])
    capabilities = installed.process([installed.entry, 'capabilities'])
    view = installed.publish('A')
    save(work/'views.json', {'A': view})
    projection = installed.view('query', view, '--sql', SQL)
    search = installed.view('search', view, '--query', keyword)
    hit = search['result']['hits'][0]
    evidence = media_summary(installed.view('media', view, '--asset-id', hit['media']['asset_id']))
    q = '/data/A/queries/'+state['queries'][0]['id']+'.json'
    vector = installed.view('vector', view, '--query', q, '--top-k', '20')
    hybrid = installed.view('hybrid', view, '--query', q, '--top-k', '20', '--text-query', state['queries'][0]['text'])
    selected = installed.view('sample', view, '--selection', '/data/A/selection.json')
    sdk = installed.process([sdk_python, Path(__file__), 'sdk', '--work-dir', work, '--keyword', keyword], 95)
    views = read_json(work/'views.json')
    reader_output = work/'reader'
    reader_command = [framework_python, ROOT/'scripts/sample_torch_client.py',
        '--view-store', work/'data/store', '--view', view,
        '--selection', work/'data/A/selection.json', '--binary', work/'prefix/lib/engine',
        '--runtime-image', RUNTIME, '--output-dir', reader_output.relative_to(ROOT), '--batch-size', '4']
    reader = installed.process(reader_command, 155)
    summary = dict(scope='small M1 preview; not full M1.5/release', views=views,
        doctor=doctor, capabilities=capabilities, query=projection, search=search,
        hit_media=evidence, vector=vector, hybrid=hybrid, sample=selected, sdk=sdk,
        reader=reader, calls=installed.calls,
        cache_state='OS/container cache UNKNOWN; fresh process is not cold storage')
    save(work/'tutorial.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'tutorial', 'sdk'])
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--inputs-root', type=Path)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--sdk-python', type=Path)
    parser.add_argument('--framework-python', type=Path)
    parser.add_argument('--keyword', default='kitchen')
    args = parser.parse_args()
    work = checked_work(args.work_dir)
    # The existing framework client deliberately restricts owned outputs here.
    work.relative_to(ROOT/'artifacts')
    if args.mode == 'prepare':
        if args.inputs_root is None or args.package is None:
            parser.error('prepare requires --inputs-root and --package')
        prepare(args.inputs_root, work, args.package)
        result = dict(prepared=str(work), inputs=read_json(work/'inputs.json'))
    elif args.mode == 'sdk':
        result = asyncio.run(sdk_flow(work, args.keyword))
    else:
        if args.sdk_python is None or args.framework_python is None:
            parser.error('tutorial requires explicit --sdk-python and --framework-python')
        result = tutorial(work, args.sdk_python, args.framework_python, args.keyword)
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
