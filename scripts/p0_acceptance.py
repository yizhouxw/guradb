#!/usr/bin/env python3
"""Run a bounded P0 concurrent workload; duration alone does not certify release."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harnesslib.acceptance_archive import archive_run
from harnesslib.policy import load
from harnesslib.runner import checkout_digest
from m0lib.kit import write
from p0lib.workload import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--duration', type=int, default=0)
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--updates', type=int, default=2)
    parser.add_argument('--transport', choices=('local','http'), default='local')
    args = parser.parse_args()
    if not (0 <= args.duration <= 86400 and 1 <= args.rounds <= 10000 and 1 <= args.updates <= 8):
        parser.error('duration 0..86400, rounds 1..10000, updates 1..8 required')
    directory = (args.run_dir or ROOT/'artifacts'/'p0'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    before = checkout_digest(ROOT, load(ROOT)[0])
    commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    try:
        result = run(directory, args.duration, args.rounds, args.updates, args.transport)
        after = checkout_digest(ROOT, load(ROOT)[0])
        if before != after or commit != subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip():
            raise RuntimeError('source changed during run; evidence invalid')
        result.update(git_commit=commit, checkout_digest=after,
                      dependency_lock_digest=hashlib.sha256((ROOT/'requirements-m1.lock').read_bytes()).hexdigest())
        write(directory/'result.json',result)
        common = Path(subprocess.check_output(['git','rev-parse','--git-common-dir'],cwd=ROOT,text=True).strip())
        if not common.is_absolute():
            common = ROOT/common
        archive = archive_run(common, 'p0', directory)
        print(json.dumps({'passed':result['passed'],'report':str(directory/'result.json'),'archive':str(archive)}))
        return 0
    except Exception:
        write(directory/'failure.json',{'passed':False,'traceback':traceback.format_exc()})
        print(traceback.format_exc(),file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
