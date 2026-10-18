"""Bounded trusted subprocess calls with deadline/cancellation and process reaping."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from modules.common.contracts import MAX_BYTES, Failure, decode_json, encoded, require


def stop_group(process):
    """Reap the leader and terminate its group, including surviving helpers."""
    try:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except PermissionError as denied:
            # Darwin may retain a zombie-only group after its leader exits.
            # Share one cleanup grace between reaping and group disappearance;
            # persistent permission denial must still fail.
            deadline = time.monotonic() + 0.1
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise denied from None
            while True:
                if time.monotonic() >= deadline:
                    raise denied from None
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    break
                except PermissionError:
                    time.sleep(min(0.005, max(0, deadline - time.monotonic())))
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def run_process(command, payload, budget):
    """Append private input/output paths to a trusted command; never accept user commands."""
    budget.check()
    raw = encoded(payload)
    require(len(raw) <= MAX_BYTES, 'resource_limit', 'native input byte budget exceeded')
    with tempfile.TemporaryDirectory(prefix='gura-native-') as directory:
        source, output, log = [Path(directory)/name for name in ('input', 'output', 'log')]
        source.write_bytes(raw)
        process = None
        try:
            with log.open('wb') as stream:
                process = subprocess.Popen([*command, str(source), str(output)], stdout=stream, stderr=stream,
                    start_new_session=True, cwd=Path(__file__).resolve().parents[2], env={k:v for k,v in os.environ.items()
                    if k in ('PATH','LANG','LC_ALL','TMPDIR','VIRTUAL_ENV')})
            while process.poll() is None:
                budget.check()
                require(log.stat().st_size <= 65536 and (not output.exists() or output.stat().st_size <= MAX_BYTES),
                        'resource_limit', 'native output/log byte budget exceeded')
                time.sleep(.01)
            budget.check()
            require(process.returncode == 0 and output.is_file(), 'native_failed', 'native subprocess failed')
            require(log.stat().st_size <= 65536, 'resource_limit')
            with output.open('rb') as stream:
                result_raw = stream.read(MAX_BYTES+1)
            require(len(result_raw) <= MAX_BYTES, 'resource_limit', 'native output byte budget exceeded')
            result = decode_json(result_raw)
            require(isinstance(result, dict) and set(result) in ({'result'}, {'error'}), 'native_failed')
            if 'error' in result:
                raise Failure(result['error'], 'native operation failed')
            budget.check()
            return result['result']
        finally:
            if process is not None:
                stop_group(process)
