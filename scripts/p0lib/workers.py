"""Lifecycle of three actual loopback worker servers for local acceptance."""
import os
from pathlib import Path
import secrets
import select
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


class RemoteWorkers:
    def __init__(self, directory, shared):
        self.secret = secrets.token_hex(32)
        self.processes, self.endpoints, self.logs = [], [], []
        try:
            for ordinal in range(3):
                root = Path(directory)/str(ordinal)
                root.mkdir(parents=True)
                log = (root/'server.log').open('wb')
                self.logs.append(log)
                process = subprocess.Popen([sys.executable,str(ROOT/'scripts/worker.py'),'--root',str(root),
                                            '--shared-root',str(shared)],cwd=ROOT,
                                           env=dict(os.environ,GURADB_WORKER_SECRET=self.secret),
                                           stdout=subprocess.PIPE,stderr=log,text=True)
                self.processes.append(process)
                if not select.select([process.stdout],[],[],10)[0]:
                    raise RuntimeError('worker startup timed out')
                value=process.stdout.readline().strip()
                if not value.isdigit():
                    raise RuntimeError('worker startup failed; see server.log')
                self.endpoints.append('http://127.0.0.1:'+value)
        except Exception:
            self.close()
            raise

    def close(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
        for process in self.processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if process.stdout:
                process.stdout.close()
        for log in self.logs:
            log.close()
