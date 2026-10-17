#!/usr/bin/env python3
"""M1 thin HTTP CLI: scan, search, export, inspect and cancel."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from clients.common.http import Client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8081')
    parser.add_argument('--token-env',default='GURADB_TOKEN')
    sub = parser.add_subparsers(dest='command',required=True)
    for name in ('scan','search','export'):
        action = sub.add_parser(name)
        action.add_argument('--dataset',required=True)
        action.add_argument('--query',default='{}',help='JSON request, as in the HTTP contract')
        action.add_argument('--view')
        action.add_argument('--no-wait',action='store_true')
    describe = sub.add_parser('describe')
    describe.add_argument('dataset')
    for name in ('status','cancel','release'):
        action = sub.add_parser(name)
        action.add_argument('job')
    args = parser.parse_args()
    try:
        client = Client(args.url,os.environ[args.token_env])
        if args.command == 'describe':
            result = client.request('GET','/v1/datasets/'+args.dataset)
        elif args.command in ('status','cancel','release'):
            suffix = '/retention' if args.command=='release' else ''
            result = client.request('GET' if args.command=='status' else 'DELETE','/v1/jobs/'+args.job+suffix)
        else:
            body = {'dataset_id':args.dataset,'query':json.loads(args.query)}
            if args.view is not None:
                body['read_view_id'] = args.view
            route = '/v1/exports' if args.command=='export' else '/v1/'+args.command
            handle = client.request('POST',route,body)
            result = handle if args.no_wait else client.wait(handle)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
        return 0
    except (RuntimeError,ValueError,KeyError) as error:
        print(str(error),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
