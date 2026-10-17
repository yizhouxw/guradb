#!/usr/bin/env python3
"""Start a trusted loopback-only worker; secret is read exclusively from environment."""
import argparse
import os
import signal
import threading
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.query.remote_worker import serve


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--shared-root', required=True)
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    server = serve(args.root, args.shared_root, os.environ['GURADB_WORKER_SECRET'], args.port)
    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(server.server_address[1], flush=True)
    try:
        server.serve_forever(poll_interval=.05)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
