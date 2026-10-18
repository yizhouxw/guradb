"""Validate the original M0 evidence bytes before publishing a v2 archive."""
import hashlib
import json
import re

from harnesslib.acceptance_archive import archive_run
from harnesslib.policy import HarnessError


SUITES = {'functional', 'performance-smoke', 'stability-component'}


def _require(condition, message):
    if not condition:
        raise HarnessError('M0 evidence: ' + message)


def _trace(content, result, prefix=''):
    try:
        trace_bytes = content[prefix + 'trace.json']
        trace = json.loads(trace_bytes)
    except (KeyError, ValueError, UnicodeError) as error:
        raise HarnessError('M0 evidence: missing or invalid ' + prefix + 'trace') from error
    _require(result.get('trace_sha256') == hashlib.sha256(trace_bytes).hexdigest(),
             prefix + 'trace checksum mismatch')
    _require(isinstance(trace, list) and bool(trace), 'empty or invalid trace')
    names = []
    for sequence, event in enumerate(trace):
        _require(isinstance(event, dict) and event.get('sequence') == sequence, 'invalid trace sequence')
        if event.get('action') == 'container_created':
            name = event.get('name')
            _require(isinstance(name, str) and re.fullmatch(r'gura-[0-9a-f]{12}-[0-9]+', name),
                     'unsafe container log name')
            names.append(name)
    _require(bool(names) and len(set(names)) == len(names), 'missing or repeated containers')
    for name in names:
        _require(prefix + name + '.log' in content, 'missing container log: ' + prefix + name)
    if 'container_log_protocol' in result:
        _require(result['container_log_protocol'] == 1, 'unsupported container log protocol')
        collected = [event for event in trace if event.get('action') == 'container_logs_collected']
        _require(len(collected) == len(names) and {event.get('name') for event in collected} == set(names),
                 'missing or duplicate log collection receipts')
        for event in collected:
            _require(event.get('returncode') == 0, 'container log extraction failed')
            _require(event.get('sha256') == hashlib.sha256(content[prefix + event['name'] + '.log']).hexdigest(),
                     'container log checksum mismatch')
    if 'build_log_sha256' in result:
        path = prefix + 'build.log'
        _require(path in content and result['build_log_sha256'] == hashlib.sha256(content[path]).hexdigest(),
                 'missing or changed ' + path)


def validate(content):
    """Validate the same byte snapshot that archive_run will preserve."""
    try:
        result = json.loads(content['result.json'])
    except (KeyError, ValueError, UnicodeError) as error:
        raise HarnessError('M0 evidence: missing or invalid result') from error
    _require(isinstance(result, dict), 'result must be an object')
    _require(result.get('passed') is True and result.get('suite') in SUITES, 'not a successful M0 suite')
    for key, length in (('git_commit', 40), ('checkout_digest', 64), ('dependency_lock_sha256', 64)):
        _require(isinstance(result.get(key), str) and re.fullmatch('[0-9a-f]{'+str(length)+'}', result[key]),
                 'missing or invalid ' + key)
    _trace(content, result)
    if 'pgwire' in result or any(path.startswith('pgwire/') for path in content):
        pgwire = result.get('pgwire')
        _require(isinstance(pgwire, dict) and pgwire.get('passed') is True, 'missing or unsuccessful PG result')
        _require(pgwire.get('container_log_protocol') == 1, 'missing or unsupported PG log protocol')
        _require('build_log_sha256' in pgwire, 'missing PG build log checksum')
        _trace(content, pgwire, 'pgwire/')


def archive(common, directory):
    return archive_run(common, 'm0', directory, validator=validate)
