"""Safe acceptance diagnostics retained on success and primary/cleanup failures."""
import json
from pathlib import Path
import traceback

ROOT = Path(__file__).resolve().parents[2]


def error_record(error):
    """Never persist exception messages, URLs, headers or source lines."""
    trace = [{'file': str(Path(item.filename).relative_to(ROOT)) if Path(item.filename).is_relative_to(ROOT)
              else Path(item.filename).name, 'line': item.lineno, 'function': item.name}
             for item in traceback.extract_tb(error.__traceback__)]
    return {'error_class': type(error).__name__, 'code': getattr(error, 'code', 'driver_assertion'),
            'trace': trace}


def write(path, record):
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def lab_record(lab, private, docker):
    value = {'private_lab': str(private/'lab') if private is not None else None,
             'public_lab_config_exported': False, 'initialized': lab is not None,
             'cleanup_confirmed': False}
    if lab is None:
        return value
    logs = [event for event in lab.trace if event['action'] == 'container_logs_collected']
    value.update(trace=lab.trace, owned_containers=len(lab.names), removed_containers=len(lab.removed),
                 logs_collected=len(logs), log_returncodes=[event['returncode'] for event in logs])
    try:
        probe = docker('network', 'ls', '--filter', 'name=^' + lab.network + '$', '--format', '{{.Name}}', check=False)
        value['network_probe_returncode'] = probe.returncode
        value['owned_network_absent'] = probe.returncode == 0 and not probe.stdout.strip()
    except Exception as error:
        value['network_probe_error'] = error_record(error)
    value['cleanup_confirmed'] = (set(lab.names) == lab.removed and len(logs) == len(lab.names)
        and all(event['returncode'] == 0 for event in logs) and value.get('owned_network_absent') is True)
    return value


def observation(path, *, reader=None, server=None, primary=None, **values):
    """No assertions here: preserving a diagnostic must not replace its cause."""
    record = {**values, 'primary_error': error_record(primary) if primary is not None else None}
    if reader is not None:
        scope = reader.scope
        record['scope'] = {name: getattr(scope, name) for name in (
            'started', 'deadline', 'object_requests', 'object_bytes', 'output_bytes', 'header_bytes',
            'wire_bytes', 'verified_bytes', 'memory_current', 'memory_peak', 'trace_dropped')}
        record.update(scope_trace=scope.trace, state_cleared=reader._state is None, poisoned=reader._failed)
    if server is not None:
        record['server'] = server.snapshot()
    write(path, record)
