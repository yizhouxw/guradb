"""One M0 scenario corpus exercised over live HTTP and Psycopg, with PG18 truth."""
from m0lib.pgwire import client, publish_auth


QUERIES = (
    'SELECT * FROM documents ORDER BY id',
    'SELECT id, title FROM documents WHERE id >= 3 AND id < 12 ORDER BY id DESC LIMIT 4',
    'SELECT id, active FROM documents WHERE active IS NULL ORDER BY id',
    'SELECT id FROM documents WHERE NOT active ORDER BY id',
    'SELECT id, title FROM documents WHERE title IS NOT NULL ORDER BY title ASC NULLS LAST, id DESC',
    'SELECT id, title FROM documents ORDER BY title DESC NULLS FIRST, id LIMIT 8',
    'SELECT id AS document_id FROM documents WHERE id < 0 ORDER BY id',
    'SELECT "id", title FROM "documents" WHERE id = 9223372036854775807 ORDER BY id',
    'SELECT id FROM documents WHERE active = true OR title IS NULL ORDER BY id',
    'SELECT id FROM documents WHERE id = NULL ORDER BY id',
    'SELECT id FROM documents WHERE NULL ORDER BY id',
    'SELECT id FROM documents WHERE NOT NULL ORDER BY id',
    'SELECT id FROM documents WHERE active OR NULL ORDER BY id',
    'SELECT id FROM documents WHERE id > -9223372036854775808 ORDER BY id',
    'SELECT id FROM documents ORDER BY id LIMIT 0',
)
# Parameters and literal oracle queries are frozen independently; never interpolate input.
PARAMETERS = (
    ('SELECT id FROM documents WHERE id = $1', [9223372036854775807],
     'SELECT id FROM documents WHERE id = 9223372036854775807'),
    ('SELECT id FROM documents WHERE id > $1 ORDER BY id', [-9223372036854775808],
     'SELECT id FROM documents WHERE id > -9223372036854775808 ORDER BY id'),
    ('SELECT id FROM documents WHERE title = $1 ORDER BY id', ['数据库'],
     "SELECT id FROM documents WHERE title = '数据库' ORDER BY id"),
    ('SELECT id FROM documents WHERE active = $1 ORDER BY id', [False],
     'SELECT id FROM documents WHERE active = false ORDER BY id'),
    ('SELECT id FROM documents WHERE title = $1 ORDER BY id', [None],
     'SELECT id FROM documents WHERE title = NULL ORDER BY id'),
    ('SELECT id FROM documents WHERE title = $1 ORDER BY id', ["' OR true; DROP TABLE documents; --"],
     'SELECT id FROM documents WHERE id < 0 ORDER BY id'),
    ('SELECT id FROM documents WHERE id > $1 AND title = $2 ORDER BY id', [2, "agent's data"],
     "SELECT id FROM documents WHERE id > 2 AND title = 'agent''s data' ORDER BY id"),
)
REJECTED = (
    'BEGIN', 'COMMIT', 'DELETE FROM documents', 'DROP TABLE documents',
    "INSERT INTO documents VALUES (1, 'x', true)", 'CREATE TABLE x(id bigint)',
    'COPY documents TO STDOUT', 'SET search_path = public',
    'SELECT * FROM pg_catalog.pg_class', 'SELECT * FROM documents; SELECT * FROM documents',
    'WITH x AS (DELETE FROM documents RETURNING *) SELECT * FROM x',
    'SELECT * FROM documents JOIN documents b ON true', 'SELECT COUNT(*) FROM documents',
    'SELECT DISTINCT id FROM documents', 'SELECT id + 1 FROM documents',
    'SELECT id FROM documents ORDER BY random()', 'SELECT * FROM documents OFFSET 1',
)


def public(rows):
    """HTTP intentionally serializes int8 as text; bool must remain bool."""
    return [[str(value) if type(value) is int else value for value in row] for row in rows]


def run(lab):
    checks = 0
    with client(lab) as sdk:
        assert sdk.connected['ok'], sdk.connected
        for sql in QUERIES:
            expected = lab.oracle(sql)
            handle, page = lab.query(sql)
            assert page['rows'] == expected and not page['truncated'], (sql, page)
            for binary in (False, True):
                result = sdk.query(sql, binary=binary)
                assert result['ok'] and public(result['rows']) == expected, (sql, result)
                assert result['columns'] == [column['name'] for column in page['columns']], result
                checks += 1
            assert handle['read_context'] == page['read_context']
        for sql, values, oracle_sql in PARAMETERS:
            expected = lab.oracle(oracle_sql)
            http_values = [{'type': 'int8', 'value': str(v)} if type(v) is int else v for v in values]
            _, page = lab.query(sql, parameters=http_values)
            assert page['rows'] == expected, (sql, page)
            sdk_sql = sql.replace('$1', '%s').replace('$2', '%s')
            for binary in (False, True):
                result = sdk.query(sdk_sql, parameters=values, prepare=True, binary=binary)
                assert result['ok'] and public(result['rows']) == expected, (sql, result)
                checks += 1
        for sql in REJECTED:
            status, body = lab.http('POST', '/v1/queries', {'sql': sql})
            assert status in (400, 404) and 'error' in body, (sql, status, body)
            result = sdk.query(sql)
            assert result['ok'] is False and result['sqlstate'] in ('0A000', '42501', '42P01'), (sql, result)
            # Rejection must leave the same SDK connection usable.
            assert sdk.query('SELECT id FROM documents WHERE id = 2')['rows'] == [[2]]
            checks += 1
        # Both paths recheck a shared identity, including prepared statements.
        query = 'SELECT id FROM documents WHERE id = %s'
        assert sdk.query(query, parameters=[2], prepare=True)['rows'] == [[2]]
        datasets = lab.principals[0]['datasets'][:]
        try:
            lab.principals[0]['datasets'] = []
            publish_auth(lab)
            status, _ = lab.http('POST', '/v1/queries', {'sql': QUERIES[0]})
            assert status == 404, status
            denied = sdk.query(query, parameters=[2], prepare=True)
            assert not denied['ok'] and denied['sqlstate'] == '42501', denied
        finally:
            lab.principals[0]['datasets'] = datasets
            publish_auth(lab)
        assert sdk.query(query, parameters=[2], prepare=True)['rows'] == [[2]]
        assert lab.query('SELECT id FROM documents WHERE id = 2')[1]['rows'] == [['2']]
        checks += 1
    return {'passed': True, 'checks': checks, 'queries': len(QUERIES), 'parameter_cases': len(PARAMETERS),
            'rejected_cases': len(REJECTED), 'interfaces': ['HTTP', 'Psycopg 3.2.10 text/binary prepared'],
            'oracle': 'PostgreSQL 18; same immutable Parquet manifest'}
