"""PG cancellation and disconnect while real remote I/O is paused, then recovery."""
import time

from m0lib.kit import docker, laboratory, write
from m0lib.pgwire import publish_auth, LISTEN, client, expected


def pending_remote(lab):
    # Check real server-namespace TCP state to synchronize the fault after the
    # query actually started S3 I/O; thread startup alone is not proof.
    script = """from pathlib import Path
print(sum(line.split()[2].endswith(':208D') and line.split()[3] == '01'
    for p in ['/proc/net/tcp', '/proc/net/tcp6']
    for line in Path(p).read_text().splitlines()[1:]))"""
    return int(docker('exec', lab.server, 'python3', '-c', script).stdout)


def run(directory):
    with laboratory(directory) as lab:
        lab.s3()
        lab.start(pg_listen=LISTEN)
        with client(lab) as probe:
            assert probe.connected['ok']
            probe.command('raw_connect', password=lab.token)
            assert pending_remote(lab) == 0
            docker('pause', lab.store)
            try:
                probe.command('raw', mode='start_query')
                lab.wait(lambda: pending_remote(lab) > 0, 2)
                result = probe.command('raw', mode='wrong_cancel')
                assert result['messages'] == [{'type': 'pending'}], result
                lab.event('pgwire_wrong_cancel_key', source='different authenticated session', result='query_still_pending')
            finally:
                docker('unpause', lab.store)
            result = probe.command('raw', mode='collect_query')
            rows = [m['values_hex'] for m in result['messages'] if m['type'] == 'D']
            decoded = [[int(bytes.fromhex(row[0])), None if row[1] is None else bytes.fromhex(row[1]).decode(),
                        None if row[2] is None else bytes.fromhex(row[2]) == b't'] for row in rows]
            assert decoded == expected(lab.rows), decoded
            lab.event('pgwire_wrong_cancel_recover', result='full independent fixture match')
        lab.start(pg_listen=LISTEN)
        with client(lab) as sdk:
            assert sdk.connected['ok']
            # Metadata-only Parse/Describe must not require a readable S3 source.
            # The process has never read S3, so no old keepalive socket can
            # satisfy pending_remote before the tested query begins its read.
            assert pending_remote(lab) == 0
            docker('pause', lab.store)
            lab.event('pgwire_inject_remote_pause')
            try:
                metadata = sdk.command('prepare', name='no_scan', sql='SELECT id, title FROM documents WHERE id = $1')
                assert metadata['ok'] and metadata['parameter_oids'] == [20] and metadata['column_oids'] == [20, 25], metadata
                assert sdk.command('start', sql='SELECT * FROM documents ORDER BY id')['ok']
                lab.wait(lambda: pending_remote(lab) > 0)
                assert sdk.command('poll')['running']
                assert sdk.command('cancel')['ok']
                cancelled = sdk.finished()
                assert cancelled['ok'] is False and cancelled['sqlstate'] == '57014', cancelled
                lab.event('pgwire_cancel', status='57014', metadata='prepared_without_source_read')
            finally:
                docker('unpause', lab.store)
            assert sdk.query()['rows'] == expected(lab.rows)
            lab.event('pgwire_cancel_recover', connection='reused', result='independent fixture match')
            # A live session re-checks credentials rather than trusting startup auth.
            lab.principals[0]['datasets'] = []
            publish_auth(lab)
            denied = sdk.query()
            assert denied['ok'] is False and denied['sqlstate'] == '42501', denied
            lab.principals[0]['datasets'] = [lab.manifest['dataset_id']]
            publish_auth(lab)
            assert sdk.query()['rows'] == expected(lab.rows)
            lab.event('pgwire_revoke_recover', existing_session='reauthorized')
        # Keep the source paused throughout the release assertion. Two real PG
        # queries occupy both shared permits; a queued HTTP query must start
        # within 2s of losing one PG socket, before the 10s query deadline.
        lab.start(pg_listen=LISTEN)
        with client(lab) as dropped, client(lab) as held:
            assert dropped.connected['ok'] and held.connected['ok']
            assert pending_remote(lab) == 0
            docker('pause', lab.store)
            queued = None
            try:
                assert dropped.command('start', sql='SELECT * FROM documents ORDER BY id')['ok']
                assert held.command('start', sql='SELECT * FROM documents ORDER BY id')['ok']
                lab.wait(lambda: pending_remote(lab) >= 2, 2)
                assert dropped.command('poll')['running']
                assert held.command('poll')['running']
                queued = lab.submit()
                path = '/v1/queries/' + queued['query_id']
                assert lab.http('GET', path)[1]['status'] == 'queued'
                started = time.perf_counter()
                dropped.kill()
                lab.wait(lambda: lab.http('GET', path)[1]['status'] == 'running', 2)
                elapsed = (time.perf_counter() - started) * 1000
                assert elapsed < 2000, elapsed
                assert held.command('poll')['running']
                lab.event('pgwire_disconnect', pending_remote_io=True, queued_http='running_before_source_resumes',
                          permit_released_ms=elapsed, query_deadline_ms=10000)
            finally:
                if queued is not None:
                    lab.http('DELETE', '/v1/queries/' + queued['query_id'])
                held.command('cancel')
                held.finished()
                docker('unpause', lab.store)
        with client(lab) as recovered:
            assert recovered.connected['ok'] and recovered.query()['rows'] == expected(lab.rows)
            assert lab.query()[1]['rows'] == [[str(r['id']), r['title'], r['active']] for r in lab.rows]
        lab.event('pgwire_disconnect_recover', pg='succeeded', http='succeeded')
        lab.start(pg_listen=LISTEN)
        with client(lab) as restarted:
            assert restarted.connected['ok'] and restarted.query()['rows'] == expected(lab.rows)
        lab.event('pgwire_restart', result='same independent fixture')
        return {'passed': True, 'seed': 0, 'trace': 'pgwire/trace.json', 'events': len(lab.trace),
                'scope': 'real PG sessions + paused S3, cancellation, socket loss, revoke and restart; no distributed/soak claim'}
