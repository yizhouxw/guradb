#!/usr/bin/env python3
"""Run real M2 acceptance with per-code evidence, never synthesize success."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from harnesslib.acceptance_archive import archive_run
from harnesslib.policy import load
from harnesslib.runner import checkout_digest
from m0lib.kit import write


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suite',choices=['functional','performance-smoke','stability-component'])
    parser.add_argument('--run-dir',type=Path)
    args=parser.parse_args()
    directory=(args.run_dir or ROOT/'artifacts'/'m2'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+args.suite)).resolve()
    directory.mkdir(parents=True,exist_ok=False)
    driver={'functional':'tests/functional/m2.py','performance-smoke':'tests/performance/component/m2.py',
            'stability-component':'tests/faults/component/m2.py'}[args.suite]
    before=checkout_digest(ROOT,load(ROOT)[0])
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    try:
        result=runpy.run_path(str(ROOT/driver))['run'](directory)
        if args.suite == 'functional':
            from tests.functional.incremental import run as incremental_run
            from tests.functional.writer import run as writer_run
            result['incremental'] = incremental_run(directory/'incremental')
            from tests.functional.incremental_s3 import run as incremental_s3_run
            result['incremental_s3'] = incremental_s3_run(directory/'incremental-s3')
            result['writer'] = writer_run(directory/'writer')
        after=checkout_digest(ROOT,load(ROOT)[0])
        if before != after or commit != subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip():
            raise RuntimeError('code changed while M2 acceptance was running; evidence invalid')
        result.update(checkout_digest=after, git_commit=commit,
                      requirements_sha256=hashlib.sha256((ROOT/'requirements-m1.lock').read_bytes()).hexdigest())
        write(directory/'result.json',result)
        common=Path(subprocess.check_output(['git','rev-parse','--git-common-dir'],cwd=ROOT,text=True).strip())
        if not common.is_absolute():common=ROOT/common
        archive = archive_run(common, 'm2', directory)
        print(json.dumps({'passed':result['passed'],'evidence':str(directory/'result.json'),'archive':str(archive)}))
        return 0 if result['passed'] else 1
    except Exception:
        write(directory/'failure.json',{'passed':False,'traceback':traceback.format_exc()})
        print(traceback.format_exc(),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
