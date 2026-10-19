"""Real object mutation, authorization, worker cancellation, TTL and restart faults."""
import time
import hashlib
import secrets
from m0lib.pgwire import publish_auth
from m0lib.kit import laboratory, truth, docker


def run(directory):
    with laboratory(directory) as lab:
        lab.s3()
        lab.start()
        before, page = lab.query()
        baseline = page['read_context']
        path = '/v1/queries/' + before['query_id']
        first = lab.manifest['files'][0]
        raw = (lab.directory/'objects'/first['key']).read_bytes()
        lab.client.put_object(Bucket='m0-data', Key=first['key'], Body=bytes([raw[0]^1]) + raw[1:])
        lab.event('inject_overwrite_same_length')
        outcome = lab.terminal(lab.submit())
        assert outcome['status'] == 'failed' and outcome['error']['code'] == 'source_invalid', outcome
        assert lab.http('GET', path + '/results')[1]['rows'] == truth(lab.rows)
        lab.client.put_object(Bucket='m0-data', Key=first['key'], Body=raw)
        assert lab.query()[1]['read_context'] == baseline
        lab.event('recover_overwrite', result='same view restored, published result unchanged')
        lab.client.delete_object(Bucket='m0-data', Key=first['key'])
        lab.event('inject_delete')
        outcome = lab.terminal(lab.submit())
        assert outcome['status'] == 'failed' and outcome['error']['code'] == 'source_unavailable', outcome
        lab.client.put_object(Bucket='m0-data', Key=first['key'], Body=raw)
        assert lab.query()[1]['rows'] == truth(lab.rows)
        lab.event('recover_delete')
        lab.principals[0]['datasets'] = []
        publish_auth(lab)
        assert lab.http('GET', path+'/results')[0] == 404
        lab.event('inject_revoke', result='cached result denied')
        lab.principals[0]['datasets'] = [lab.manifest['dataset_id']]
        publish_auth(lab)
        code, restored = lab.http('GET', path+'/results')
        assert code == 200, (code, restored)
        # Hold actual remote I/O. Two workers consume the semaphore; third is queued.
        docker('pause', lab.store)
        lab.event('inject_remote_pause')
        try:
            a = lab.submit()
            b = lab.submit()
            lab.wait(lambda: all(lab.http('GET', '/v1/queries/'+q['query_id'])[1]['status']=='running' for q in [a,b]))
            queued = lab.submit()
            # A second credential for the same subject can inspect that subject's
            # task while the submitting credential loses its execution grant.
            audit_token = secrets.token_hex(24)
            auditor = dict(lab.principals[0], token_sha256=hashlib.sha256(audit_token.encode()).hexdigest())
            queued_path = '/v1/queries/' + queued['query_id']
            assert lab.http('GET', queued_path)[1]['status'] == 'queued'
            assert lab.http('GET', queued_path+'/results')[0] == 409
            assert lab.http('DELETE', queued_path)[0] == 202
            assert lab.terminal(queued)['status'] == 'cancelled'
            for q in [a,b]:
                assert lab.http('DELETE', '/v1/queries/'+q['query_id'])[0] == 202
                assert lab.terminal(q)['status'] == 'cancelled'
                assert lab.http('DELETE', '/v1/queries/'+q['query_id'])[1]['status'] == 'cancelled'
            # Queue the revocation check behind paused running workers.
            # Running cancellations above release permits; a fresh held pair makes
            # the next queued execution checkpoint deterministic.
            held = [lab.submit(), lab.submit()]
            lab.wait(lambda: all(lab.http('GET','/v1/queries/'+q['query_id'])[1]['status']=='running' for q in held))
            revoke_task = lab.submit()
            lab.principals[0]['datasets'] = []
            publish_auth(lab, [*lab.principals, auditor])
            for q in held:
                lab.http('DELETE','/v1/queries/'+q['query_id'],token=audit_token)
            def revoked_done():
                code, value = lab.http('GET','/v1/queries/'+revoke_task['query_id'],token=audit_token)
                assert code == 200
                return value if value['status'] == 'failed' else None
            denied = lab.wait(revoked_done)
            assert denied['error']['code'] == 'forbidden', denied
            lab.principals[0]['datasets'] = [lab.manifest['dataset_id']]
            publish_auth(lab)
            lab.event('queued_execution_reauthorization', result='forbidden before source read')
            timed = lab.terminal(lab.submit(timeout_ms=100))
            assert timed['status'] == 'failed' and timed['error']['code'] == 'timeout', timed
            lab.event('cancel_timeout_assertions', queued='cancelled', running='cancelled', deadline='timeout')
        finally:
            docker('unpause', lab.store)
        assert lab.query()[1]['rows'] == truth(lab.rows)
        lab.event('recover_remote_pause')
        old = lab.query()[0]
        lab.start()
        assert lab.http('GET', '/v1/queries/'+old['query_id'])[0] == 404
        new, page = lab.query()
        assert page['read_context'] == baseline and page['rows'] == truth(lab.rows)
        lab.event('restart', old_handle='404', data_view='unchanged')
        lab.start({'retention_seconds': 1, 'handles': 2})
        expired = lab.query()[0]
        time.sleep(1.1)
        assert lab.http('GET', '/v1/queries/'+expired['query_id'])[0] == 410
        assert lab.http('GET', '/v1/queries/'+expired['query_id'], token=lab.other_token)[0] == 404
        lab.query()
        lab.query()
        assert lab.http('POST','/v1/queries',{'sql':'SELECT * FROM documents'})[0] == 429
        lab.event('ttl_capacity', expired='410', wrong_subject='404', capacity='429')
        return {'suite': 'stability-component', 'passed': True, 'seed': 0, 'trace': 'trace.json', 'events': len(lab.trace),
                'scope': 'M0 single process + real S3 faults; no distributed/soak claim'}
