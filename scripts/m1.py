#!/usr/bin/env python3
"""M1 operator entry point. PG DSN and S3 credentials come only from environment."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from modules.catalog.control import Control
from modules.catalog.managed import Managed
from modules.connectors.writer import Writer
from modules.common.contracts import Failure
from modules.gateway.m1 import Server
from modules.query.service import Service
from modules.query.snapshot import collect, construct, publish
from modules.query.incremental import refresh, progress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn-env',default='GURADB_PG_DSN')
    parser.add_argument('--root',type=Path,default=Path('data/m1'))
    sub = parser.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    register = sub.add_parser('register')
    register.add_argument('--config',type=Path,required=True)
    for name in ('grant','revoke'):
        action = sub.add_parser(name)
        action.add_argument('--tenant',required=True)
        action.add_argument('--subject',required=True)
        action.add_argument('--dataset',required=True)
        if name=='grant':
            action.add_argument('--token-sha256',required=True)
    build = sub.add_parser('snapshot', aliases=['refresh'])
    build.add_argument('--dataset',required=True)
    build.add_argument('--operation',required=True)
    build.add_argument('--target',type=Path,required=True)
    build.add_argument('--s3-endpoint')
    for name in ('run','progress','publish','pin','unpin','gc'):
        action = sub.add_parser(name)
        action.add_argument('run')
        if name=='publish':
            action.add_argument('--expected-epoch',type=int,required=True)
        if name in ('pin','unpin'):
            action.add_argument('--owner',required=True)
    for name in ('managed-init','append'):
        action = sub.add_parser(name)
        action.add_argument('--name',required=True)
        if name == 'append':
            action.add_argument('--operation',required=True)
            action.add_argument('--rows',type=Path,required=True)
    serve = sub.add_parser('serve')
    serve.add_argument('--host',default='127.0.0.1')
    serve.add_argument('--port',type=int,default=8081)
    serve.add_argument('--workers',type=int,choices=(0,3),default=0)
    args = parser.parse_args()
    try:
        control = Control(os.environ[args.dsn_env])
        if args.command=='init':
            control.initialize()
            result={'initialized':True}
        elif args.command=='register':
            config=json.loads(args.config.read_text())
            control.register(**config)
            result={'registered':True}
        elif args.command=='grant':
            control.grant(args.token_sha256,args.tenant,args.subject,args.dataset)
            result={'granted':True}
        elif args.command=='revoke':
            control.revoke(args.tenant,args.subject,args.dataset)
            result={'revoked':True}
        elif args.command in ('snapshot','refresh'):
            s3=None
            if args.s3_endpoint:
                import boto3
                from botocore.config import Config
                s3=boto3.client('s3',endpoint_url=args.s3_endpoint,
                                config=Config(connect_timeout=2,read_timeout=3,retries={'max_attempts':0}))
            builder=construct if args.command=='snapshot' else refresh
            result=builder(control,args.dataset,args.operation,json.loads(args.target.read_text()),args.root,s3)
        elif args.command=='publish':
            result={'epoch':publish(control,args.run,args.expected_epoch)}
        elif args.command in ('pin','unpin'):
            getattr(control,args.command)(args.run,args.owner)
            result={args.command:True}
        elif args.command=='gc':
            collect(control,args.run,args.root)
            result={'retired':True}
        elif args.command in ('managed-init','append'):
            managed=Managed(os.environ[args.dsn_env])
            writer=Writer(args.root,args.name)
            if args.command=='managed-init':
                managed.initialize()
                writer.initialize(managed)
                result={'initialized':True,'table':args.name}
            else:
                from modules.common.contracts import decode_json, require
                require(args.rows.stat().st_size <= 2 << 20, 'resource_limit')
                result=writer.append(managed,args.operation,decode_json(args.rows.read_bytes()))
        elif args.command=='progress':
            result=progress(control,args.run)
        elif args.command=='run':
            result=control.run(args.run)
        else:
            service=Service(control,args.root/'jobs',workers=args.workers)
            server=Server((args.host,args.port),service)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
                service.close()
            return 0
        print(json.dumps(result,default=str,ensure_ascii=False))
        return 0
    except Failure as error:
        print(json.dumps(error.envelope()),file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps(Failure('operator_failed','operation failed; reconcile operation/run ID before retry').envelope()),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
