"""Fixed query.worker entrypoint that reaps its group if its HTTP owner disappears."""
import os
import signal
import subprocess
import threading
import time

from modules.common.contracts import Failure


def descendants():
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid='], capture_output=True, text=True, check=True)
    pairs = [tuple(map(int, line.split())) for line in result.stdout.splitlines() if line.strip()]
    found = {os.getpid()}
    while True:
        expanded = found | {pid for pid,parent in pairs if parent in found}
        if expanded == found:
            return found - {os.getpid()}
        found = expanded


def main():
    owner = int(os.environ.pop('GURADB_PARENT_PID'))
    finished = threading.Event()

    def abandoned(*_):
        raise Failure('worker_abandoned', 'HTTP worker owner disappeared')

    signal.signal(signal.SIGTERM, abandoned)

    def watch():
        while not finished.wait(.02):
            if os.getppid() != owner:
                # Interrupt Python so nested native-process finally blocks can reap.
                children = descendants()
                os.kill(os.getpid(), signal.SIGTERM)
                if not finished.wait(.5):
                    children |= descendants()
                    for pid in children:
                        try:
                            os.killpg(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    os.killpg(os.getpid(), signal.SIGKILL)
                return

    threading.Thread(target=watch, daemon=True).start()
    try:
        from modules.query.worker import main as worker_main
        worker_main()
    finally:
        finished.set()


if __name__ == '__main__':
    main()
