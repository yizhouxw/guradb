#!/usr/bin/env python3
"""Offline local joint recovery. DSNs are read only from environment variables."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.catalog.recovery import backup, restore, verify
from modules.common.contracts import Failure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn-env', default='GURADB_PG_DSN')
    sub = parser.add_subparsers(dest='command', required=True)
    b = sub.add_parser('backup')
    b.add_argument('--root', required=True, type=Path)
    b.add_argument('--destination', required=True, type=Path)
    b.add_argument('--writes-frozen', action='store_true')
    v = sub.add_parser('verify')
    v.add_argument('--backup', required=True, type=Path)
    r = sub.add_parser('restore')
    r.add_argument('--backup', required=True, type=Path)
    r.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'backup':
            result = backup(os.environ[args.dsn_env], args.root, args.destination, args.writes_frozen)
        elif args.command == 'verify':
            result = {'verified': True, 'files': len(verify(args.backup)['files'])}
        else:
            result = restore(os.environ[args.dsn_env], args.backup, args.destination)
        print(json.dumps(result))
        return 0
    except Failure as error:
        print(json.dumps(error.envelope()))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
