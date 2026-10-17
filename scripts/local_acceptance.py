#!/usr/bin/env python3
"""Execute local recovery or operational inspection with code-bound evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
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
    parser.add_argument('suite',choices=('recovery','inspection','rebuild'))
    parser.add_argument('--run-dir',type=Path)
    args=parser.parse_args()
    directory=(args.run_dir or ROOT/'artifacts'/args.suite/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')).resolve()
    directory.mkdir(parents=True,exist_ok=False)
    before=checkout_digest(ROOT,load(ROOT)[0])
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    try:
        if args.suite=='recovery':
            from tests.functional.m4 import run
        elif args.suite=='inspection':
            from tests.functional.inspection import run
        else:
            from tests.functional.rebuild import run
        result=run(directory)
        after=checkout_digest(ROOT,load(ROOT)[0])
        if before!=after or commit!=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip():
            raise RuntimeError('source changed during acceptance; evidence invalid')
        if result.get('passed') is not True:
            raise RuntimeError('driver did not report success')
        result.update(git_commit=commit,checkout_digest=after,
                      dependency_lock_digest=hashlib.sha256((ROOT/'requirements-m1.lock').read_bytes()).hexdigest())
        write(directory/'result.json',result)
        common=Path(subprocess.check_output(['git','rev-parse','--git-common-dir'],cwd=ROOT,text=True).strip())
        if not common.is_absolute():common=ROOT/common
        archive = archive_run(common, 'local', directory)
        print(json.dumps({'passed':True,'report':str(directory/'result.json'),'archive':str(archive)}))
        return 0
    except Exception:
        write(directory/'failure.json',{'passed':False,'traceback':traceback.format_exc()})
        print(traceback.format_exc(),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
