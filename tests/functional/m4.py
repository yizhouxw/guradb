"""Real PG/local-object joint recovery drill; no fake database or source reader."""
import json
from pathlib import Path
import shutil
import time

import psycopg

from m0lib.kit import DATASET, laboratory, write
from m1lib.fixtures import feature_file, iceberg, pg, target
from modules.catalog.managed import Managed
from modules.connectors.writer import Writer
from modules.catalog.control import Control
from modules.catalog.recovery import backup, restore, verify
from modules.common.contracts import Budget, Failure, digest, encoded
from modules.index.retrieval import load_bundle, search
from modules.query.service import Service
from modules.query.snapshot import construct, publish


def rejects(call, code):
    try:
        call()
    except Failure as error:
        assert error.code == code, (error.code, code)
        return
    raise AssertionError('unsafe recovery accepted')


def run(directory):
    directory = Path(directory).resolve()
    with laboratory(directory) as lab:
        control, _, dsn = pg(lab)
        lake = directory/'lake'
        table, _, rows = iceberg(lake)
        media_bytes = b'local-recovery-media'
        media_path = lake/'media.bin'
        media_path.write_bytes(media_bytes)
        media = {'uri': media_path.as_uri(), 'sha256': digest(media_bytes), 'size_bytes': len(media_bytes)}
        features = feature_file(lake, rows, media=media)
        root = directory/'state'
        control.register(DATASET, 'tenant', 'documents', {'root': lake.as_uri(), 'key_field': 'id', 'text_field': 'title'})
        built = construct(control, DATASET, 'snapshot', target(table, features), root/'builds')
        publish(control, built['id'], 0)
        token = 'local-recovery-test'
        control.grant(digest(token.encode()), 'tenant', 'reader', DATASET)
        principal = control.principal(token)
        service = Service(control, root/'results')
        try:
            rejects(lambda: backup(dsn, root, directory/'running-backup', frozen=True), 'recovery_busy')
            job = service.submit(principal, DATASET, 'export', {})
            for _ in range(200):
                result = service.jobs.get(job['id'], principal)
                if result['status'] not in ('queued', 'running'):
                    break
                time.sleep(.05)
            assert result['status'] == 'succeeded', result
        finally:
            service.close()
        managed = Managed(dsn)
        managed.initialize()
        writer = Writer(root/'sources'/'documents', 'managed_docs')
        writer.initialize(managed)
        managed_rows = [{'id': 91, 'title': str(root/'nonexistent-title'), 'active': True}]
        managed_result = writer.append(managed, 'first', managed_rows)
        managed_features = feature_file(writer.root, managed_rows)
        managed_dataset = '00000000-0000-0000-0000-000000000090'
        control.register(managed_dataset, 'tenant', 'managed_backup',
                         {'root': writer.root.as_uri(), 'key_field': 'id', 'text_field': 'title'})
        managed_built = construct(control, managed_dataset, 'managed-snapshot', target(writer.table(), managed_features), root/'builds')
        publish(control, managed_built['id'], 0)
        control.revoke('tenant', 'reader', DATASET)
        original = load_bundle(control.run(built['id'])['artifact'], Budget())
        expected = search(original, {'text': 'alpha'}, Budget())
        archive = directory/'backup'
        rejects(lambda: backup(dsn, root, directory/'not-frozen'), 'writes_not_frozen')
        with control.transaction() as conn:
            conn.execute('UPDATE gura_managed.tables SET root=%s', (str(root),))
        rejects(lambda: backup(dsn, root, directory/'source-root-equality', frozen=True), 'unsafe_path')
        with control.transaction() as conn:
            conn.execute('UPDATE gura_managed.tables SET root=%s', (str(writer.root),))
        evidence = backup(dsn, root, archive, frozen=True)
        assert verify(archive)['version'] == 1
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute('CREATE DATABASE recovery_drill')
        restored_dsn = dsn.replace('dbname=postgres', 'dbname=recovery_drill')
        destination = directory/'restored'
        restore(restored_dsn, archive, destination)
        restored = Control(restored_dsn)
        assert restored.dataset(DATASET)['published'] == built['id']
        with restored.transaction() as conn:
            assert conn.execute('SELECT count(*) AS n FROM gura_m1.pins').fetchone()['n'] == 1
            assert conn.execute('SELECT owner FROM gura_m1.pins').fetchone()['owner'] == str(job['id'])
        # Destroy original authoritative bytes; all restored references must stand alone.
        shutil.rmtree(root)
        shutil.rmtree(lake)
        restored_writer = Writer(destination/'sources'/'documents', 'managed_docs')
        assert restored_writer.append(Managed(restored_dsn), 'first', managed_rows)['snapshot_id'] == managed_result['snapshot_id']
        restored_business = load_bundle(restored.run(managed_built['id'])['artifact'], Budget())
        assert restored_business['rows'][0]['values']['title'] == str(root/'nonexistent-title')
        recovered_table = restored_writer.table()
        recovered_features = feature_file(restored_writer.root, managed_rows)
        restored.register('00000000-0000-0000-0000-000000000091', 'tenant', 'restored_managed',
                          {'root': restored_writer.root.as_uri(), 'key_field': 'id', 'text_field': 'title'})
        managed_view = construct(restored, '00000000-0000-0000-0000-000000000091', 'restored-source',
                                 target(recovered_table, recovered_features), destination/'builds')
        assert load_bundle(managed_view['artifact'], Budget())['rows'][0]['values']['title'] == str(root/'nonexistent-title')
        restored_writer.append(Managed(restored_dsn), 'second', [{'id': 92, 'title': 'new alpha', 'active': False}])
        assert sorted(restored_writer.table().scan().to_arrow().to_pylist(), key=lambda r: r['id']) == managed_rows + [{'id': 92, 'title': 'new alpha', 'active': False}]
        bundle = load_bundle(restored.run(built['id'])['artifact'], Budget())
        assert bundle['context'] == original['context']
        assert search(bundle, {'text': 'alpha'}, Budget()) == expected
        fresh = Service(restored, destination/'results')
        try:
            restored_principal = restored.principal(token)
            rejects(lambda: fresh.describe(restored_principal, DATASET), 'not_found')
            rejects(lambda: fresh.jobs.get(job['id'], restored_principal), 'not_found')
            restored.grant(digest(token.encode()), 'tenant', 'reader', DATASET)
            recovered_job = fresh.jobs.get(job['id'], restored_principal)
            from modules.storage.objects import get
            export_result = json.loads(get(recovered_job['result']))
            export_manifest = json.loads(get(export_result['manifest']))
            assert export_manifest['read_context'] == original['context']
            assert get(export_manifest['parquet']) == get(export_result['parquet'])
            assert fresh.media(job['id'], restored_principal, media['sha256']) == media_bytes
            assert fresh.describe(restored_principal, DATASET)['read_context'] == original['context']
            restored.revoke('tenant', 'reader', DATASET)
            rejects(lambda: fresh.media(job['id'], restored_principal, media['sha256']), 'not_found')
            rejects(lambda: fresh.describe(restored_principal, DATASET), 'not_found')
        finally:
            fresh.close()
        rejects(lambda: restore(restored_dsn, archive, directory/'occupied-db'), 'restore_not_empty')
        raw_manifest = (archive/'manifest.json').read_bytes()
        raw_complete = (archive/'COMPLETE.json').read_bytes()
        for change, code in ((lambda m: m.update(version=2), 'incompatible_backup'),
                             (lambda m: m['files'][0].update(path='../escape'), 'unsafe_path')):
            modified = json.loads(raw_manifest)
            change(modified)
            payload = encoded(modified)
            (archive/'manifest.json').write_bytes(payload)
            (archive/'COMPLETE.json').write_bytes(encoded({'version': 1, 'manifest_sha256': digest(payload)}))
            rejects(lambda: verify(archive), code)
        (archive/'manifest.json').write_bytes(raw_manifest)
        (archive/'COMPLETE.json').write_bytes(raw_complete)
        (archive/'objects'/'unsafe-link').symlink_to('/etc/passwd')
        rejects(lambda: verify(archive), 'unsafe_path')
        (archive/'objects'/'unsafe-link').unlink()
        first = verify(archive)['files'][0]['path']
        (archive/'objects'/first).write_bytes(b'corrupt')
        rejects(lambda: verify(archive), 'backup_corrupt')
        result = {'passed': True, 'checks': 25, 'backup': evidence,
                  'scope': 'offline-local-pg-and-managed-copy; no HA or cross-host DR'}
        write(directory/'result.json', result)
        return result
