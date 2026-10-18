"""Real psql18 and psycopg3 acceptance for the bounded PostgreSQL wire endpoint."""
from m0lib.kit import DATASET, laboratory, write
from m0lib.pgwire import publish_auth, LISTEN, client, expected, psql
import runpy
from m0lib.kit import ROOT


def denied(result, *codes):
    assert result['ok'] is False and result['sqlstate'] in codes, result


def run(directory):
    checks = 0
    with laboratory(directory) as lab:
        lab.postgres()
        lab.start(pg_listen=LISTEN)
        simple = psql(lab, 'SELECT id, title, active FROM documents ORDER BY id;')
        assert simple.returncode == 0, simple.stderr
        lines = ['\t'.join('<NULL>' if v is None else ('t' if v else 'f') if isinstance(v, bool) else str(v)
                           for v in row) for row in expected(lab.rows)]
        assert simple.stdout.splitlines() == lines, simple.stdout
        # psql scripts send separate simple queries; each gets its own ReadyForQuery.
        simple = psql(lab, 'SELECT id FROM documents WHERE id = 1;\nSELECT id FROM documents WHERE id = 2;')
        assert simple.returncode == 0 and simple.stdout.splitlines() == ['1', '2'], simple
        checks += 2
        with client(lab, sslmode='prefer') as sdk:
            assert sdk.connected['ok'], sdk.connected
            for binary in [False, True]:
                result = sdk.query(binary=binary)
                assert result['ok'] and result['rows'] == expected(lab.rows), result
                assert result['oids'] == [20, 25, 16], result
                assert result['columns'] == ['id', 'title', 'active'], result
                assert result['status'] == 'SELECT 20', result
                checks += 1
            for sql in [
                'SELECT id, title FROM documents WHERE id >= 3 AND id < 12 ORDER BY id DESC LIMIT 4',
                'SELECT id, active FROM documents WHERE active IS NULL ORDER BY id',
                'SELECT id, title FROM documents ORDER BY title DESC NULLS FIRST, id LIMIT 8',
                'SELECT id FROM documents WHERE NOT active ORDER BY id',
                'SELECT id FROM documents WHERE id < 0 ORDER BY id',
            ]:
                result = sdk.query(sql)
                normalized = [[str(v) if isinstance(v, int) and not isinstance(v, bool) else v for v in row] for row in result['rows']]
                assert normalized == lab.oracle(sql), (sql, result)
                checks += 1
            for sql, params, rows in [
                ('SELECT id FROM documents WHERE id = %s', [9223372036854775807], [[9223372036854775807]]),
                ('SELECT id FROM documents WHERE id > %s ORDER BY id', [-9223372036854775808], [[r['id']] for r in lab.rows]),
                ('SELECT id FROM documents WHERE id = %s', [{'type': 'int2', 'value': 3}], [[3]]),
                ('SELECT id FROM documents WHERE id = %s', [{'type': 'int4', 'value': 3}], [[3]]),
                ('SELECT id FROM documents WHERE id = %s', [{'type': 'int8', 'value': 3}], [[3]]),
                ('SELECT title FROM documents WHERE title = %s ORDER BY id', ['数据库'], [[r['title']] for r in lab.rows if r['title'] == '数据库']),
                ('SELECT id FROM documents WHERE title = %s', [None], []),
                ('SELECT id FROM documents WHERE active = %s ORDER BY id', [False], [[r['id']] for r in lab.rows if r['active'] is False]),
                ('SELECT id FROM documents WHERE title = %s', ["' OR true; DROP TABLE documents; --"], []),
            ]:
                for binary in [False, True]:
                    result = sdk.query(sql, parameters=params, binary=binary, prepare=True)
                    assert result['ok'] and result['rows'] == rows, (sql, params, result)
                    checks += 1
            # The same named statement is rebound; results must reflect the new parameter.
            for value in [2, 8, 3]:
                result = sdk.query('SELECT id FROM documents WHERE id = %s', parameters=[value], prepare=True)
                assert result['ok'] and result['rows'] == [[value]], result
                checks += 1
            for sql in ['BEGIN', 'COMMIT', 'SET search_path = public', 'DELETE FROM documents',
                        "INSERT INTO documents VALUES (1, 'x', true)", 'CREATE TABLE x(id bigint)',
                        'COPY documents TO STDOUT', 'SELECT * FROM pg_catalog.pg_class',
                        'SELECT * FROM documents; SELECT * FROM documents']:
                denied(sdk.query(sql), '0A000', '42501')
                assert sdk.query('SELECT id FROM documents WHERE id = 2')['rows'] == [[2]]
                checks += 1
            denied(sdk.query('SELECT id FROM documents WHERE id = %s', parameters=['bad']), '22023', '0A000', '42804')
            assert sdk.query('SELECT id FROM documents WHERE id = 2')['rows'] == [[2]]
            prepared = sdk.command('prepare', name='metadata', sql='SELECT id, title FROM documents WHERE id = $1 AND title = $2')
            assert prepared == {'ok': True, 'sqlstate': None, 'parameter_oids': [20, 25], 'column_oids': [20, 25]}, prepared
            repeated = sdk.command('prepare', name='repeated', sql='SELECT id FROM documents WHERE id = $1 OR id > $1')
            assert repeated['ok'] and repeated['parameter_oids'] == [20], repeated
            denied(sdk.command('prepare', name='unknown', sql='SELECT id FROM documents WHERE $1 = $1'), '42P18')
            denied(sdk.command('prepare', name='conflict', sql='SELECT id FROM documents WHERE id = $1 AND title = $1'), '22023', '42804')
            checks += 5
            # Revocation applies to already connected sessions and cached prepared statements.
            lab.principals[0]['datasets'] = []
            publish_auth(lab)
            denied(sdk.query('SELECT id FROM documents WHERE id = %s', parameters=[2], prepare=True), '42501')
            with client(lab, password=lab.other_token) as other:
                assert other.connected['ok'] and other.query()['rows'] == expected(lab.rows)
            lab.principals[0]['datasets'] = [DATASET]
            publish_auth(lab)
            assert sdk.query('SELECT id FROM documents WHERE id = %s', parameters=[2], prepare=True)['rows'] == [[2]]
            checks += 2
        for options, code in [({'password': 'wrong'}, '28P01'), ({'user': 'missing'}, '28P01'),
                              ({'database': 'other'}, '3D000'), ({'autocommit': False}, None)]:
            with client(lab, **options) as sdk:
                if code:
                    # libpq connection failures become OperationalError without
                    # an exposed SQLSTATE. Assert rejection here and read the
                    # actual startup ErrorResponse independently over TCP below.
                    assert not sdk.connected['ok'] and sdk.connected['type'] == 'OperationalError', sdk.connected
                    raw = sdk.command('raw_connect', password=options.get('password', lab.token),
                                      user=options.get('user', 'reader'), database=options.get('database', 'guradb'))
                    assert raw['messages'][-1] == {'type': 'E', 'sqlstate': code}, raw
                else:
                    assert sdk.connected['ok']
                    denied(sdk.query(), '0A000')
                checks += 1
        checks += runpy.run_path(str(ROOT / 'tests/functional/pgwire_protocol.py'))['run'](lab)
        # pgwire must return an error instead of silently truncating a SQL result.
        lab.start({'max_rows': 7}, pg_listen=LISTEN)
        with client(lab) as sdk:
            denied(sdk.query(), '54000')
            assert sdk.query('SELECT id FROM documents ORDER BY id LIMIT 7')['rows'] == [[i] for i in range(7)]
            checks += 1
        for limits in [{'scan_bytes': 1}, {'decoded_bytes': 1}, {'result_bytes': 1}]:
            lab.start(limits, pg_listen=LISTEN)
            with client(lab) as sdk:
                denied(sdk.query(), '54000')
                checks += 1
        lab.event('pgwire_functional_passed', assertions=checks, clients=['psql18', 'psycopg3.2.10'])
        return {'passed': True, 'assertions': checks, 'clients': ['psql18', 'psycopg3.2.10'],
                'oracle': 'independent Python fixture + PostgreSQL 18', 'transport': 'container namespace loopback; no exposed port'}
