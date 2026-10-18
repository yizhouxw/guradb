"""Real socket failure, protocol resource and suspended-portal assertions."""
import json

from m0lib.kit import ROOT, RUST, docker, mapped, write
from m0lib.pgwire import publish_auth, client


def healthy(sdk):
    result = sdk.query('SELECT id FROM documents WHERE id = 2', prepare=False)
    assert result['ok'] and result['rows'] == [[2]], result


def run(lab):
    checks = 0
    with client(lab) as sdk:
        assert sdk.connected['ok']
        for mode in ['oversized', 'truncated', 'invalid_utf8']:
            result = sdk.command('raw_startup', mode=mode)
            assert result['rejected'], result
            if mode == 'invalid_utf8':
                assert result['sqlstate'] == '08P01', result
            healthy(sdk)
            checks += 1
        result = sdk.command('raw_connect', password=lab.token, encoding='LATIN1')
        assert any(m['type'] == 'E' for m in result['messages']), result
        for mode in ['oversized', 'truncated', 'invalid_utf8']:
            sdk.command('raw_connect', password=lab.token)
            result = sdk.command('raw', mode=mode)
            assert any(m['type'] in ['E', 'closed'] for m in result['messages']), result
            if mode == 'invalid_utf8':
                assert result['messages'] == [{'type': 'E', 'sqlstate': '08P01'}], result
            healthy(sdk)
            checks += 1
        for index in range(32):
            result = sdk.command('prepare', name=f'bounded_{index}', sql='SELECT id FROM documents')
            assert result['ok'], (index, result)
        result = sdk.command('prepare', name='overflow', sql='SELECT id FROM documents')
        assert not result['ok'] and result['sqlstate'] == '54000', result
        assert sdk.command('close_prepared', name='bounded_0')['ok']
        assert sdk.command('prepare', name='recovered', sql='SELECT id FROM documents')['ok']
        healthy(sdk)
        checks += 2
        sdk.command('raw_connect', password=lab.token)
        result = sdk.command('raw', mode='portal')
        assert result['messages'][-1]['type'] == 's', result
        rows = [m['values_hex'] for m in result['messages'] if m['type'] == 'D']
        assert rows == [['30', None], ['31', '62657461']], rows
        result = sdk.command('raw', mode='resume')
        assert result['messages'][-1]['type'] == 's', result
        rows = [m['values_hex'] for m in result['messages'] if m['type'] == 'D']
        assert rows == [['32', 'e695b0e68daee5ba93'], ['33', '6167656e7427732064617461']], rows
        lab.principals[0]['datasets'] = []
        publish_auth(lab)
        result = sdk.command('raw', mode='resume')
        assert result['messages'] == [{'type': 'E', 'sqlstate': '42501'}], result
        assert sdk.command('raw', mode='sync')['messages'][-1]['type'] == 'Z'
        lab.principals[0]['datasets'] = [lab.manifest['dataset_id']]
        publish_auth(lab)
        healthy(sdk)
        sdk.command('raw_connect', password=lab.token)
        assert sdk.command('raw', mode='portal')['messages'][-1]['type'] == 's'
        result = sdk.command('raw', mode='close_statement')
        assert result['messages'] == [{'type': '3'}, {'type': 'E', 'sqlstate': '34000'}], result
        sdk.command('raw_connect', password=lab.token)
        assert sdk.command('raw', mode='portal', unnamed=True)['messages'][-1]['type'] == 's'
        result = sdk.command('raw', mode='replace_unnamed')
        assert result['messages'] == [{'type': '1'}, {'type': 'E', 'sqlstate': '34000'}], result
        result = sdk.command('raw_connect', password=lab.token, version=196610)
        assert {'type': 'v', 'version': 196608} in result['messages'] and result['messages'][-1]['type'] == 'Z', result
        assert sdk.command('raw', mode='portal_capacity')['messages'] == [{'type': 'E', 'sqlstate': '54000'}]
        result = sdk.command('connection_capacity', password=lab.token)
        assert result == {'accepted': 63, 'overflow': {'type': 'E', 'sqlstate': '53300'}, 'recovered': True}, result
        checks += 8
    with client(lab, sslmode='require') as sdk:
        assert sdk.connected['ok'] is False, sdk.connected
        checks += 1
    config = json.loads((lab.directory / 'server.json').read_text())
    config['pg_listen'] = '0.0.0.0:5433'
    path = lab.directory / 'invalid-pg-listen.json'
    write(path, config)
    invalid = lab.container(RUST, '/workspace/target/debug/guradb', '--config', mapped(path),
                            options=('-v', f'{ROOT}:/workspace:ro'))
    lab.wait(lambda: docker('inspect', '--format', '{{.State.Running}}', invalid).stdout.strip() == 'false', 3)
    assert docker('inspect', '--format', '{{.State.ExitCode}}', invalid).stdout.strip() == '1'
    log = docker('logs', invalid).stderr
    assert 'invalid_config' in log and 'loopback' in log, log
    lab.event('pgwire_protocol_passed', checks=checks + 1, scope='real TCP and live SDK')
    return checks + 1
