#!/usr/bin/env python3
"""Inventory exact installed Python and locked Cargo components for local review."""
import argparse
from importlib import metadata
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def inventory(cargo_metadata):
    components = []
    for dist in metadata.distributions():
        name, version = dist.metadata['Name'], dist.version
        components.append({'ecosystem':'pypi','name':name,'version':version,
                           'purl':'pkg:pypi/'+name.lower().replace('_','-')+'@'+version,
                           'license_expression':dist.metadata.get('License-Expression'),
                           'license_declaration':dist.metadata.get('License'),
                           'license_classifiers':[v for v in dist.metadata.get_all('Classifier',[]) if v.startswith('License ::')],
                           'evidence':'installed distribution METADATA; declarations require review'})
    locked = tomllib.loads((ROOT/'Cargo.lock').read_text())['package']
    observed = {(p['name'],p['version']):p for p in cargo_metadata['packages']}
    for package in locked:
        identity = (package['name'],package['version'])
        found = observed.get(identity)
        if found is None:
            raise ValueError('locked Cargo package absent from metadata: '+repr(identity))
        components.append({'ecosystem':'cargo','name':package['name'],'version':package['version'],
                           'purl':'pkg:cargo/'+package['name']+'@'+package['version'],
                           'source':package.get('source','workspace'), 'checksum_sha256':package.get('checksum'),
                           'license_expression':found.get('license'), 'license_file':found.get('license_file'),
                           'evidence':'Cargo.lock checksum + cargo metadata manifest declaration'})
    locks = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.glob('requirements*.lock'))}
    locks['Cargo.lock'] = hashlib.sha256((ROOT/'Cargo.lock').read_bytes()).hexdigest()
    missing = [c['purl'] for c in components if not any(c.get(n) for n in
               ('license_expression','license_declaration','license_classifiers','license_file'))]
    return {'schema_version':1,'format':'guradb-component-inventory-v1',
            'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'lock_sha256':locks,'components':sorted(components,key=lambda c:c['purl']),
            'scope':'installed Python environment (including development tools) and all locked Cargo packages',
            'not_included':['container OS packages','model/codec/dictionary assets not installed','future deployment images'],
            'missing_license_declarations':missing,
            'distribution_approved':False,
            'distribution_gaps':['project license decision is not authorized',
                                 'dependency license declarations require legal/distribution review',
                                 'container image SBOM and bundled NOTICE/license texts remain required']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cargo-metadata',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--require-distribution-approved',action='store_true')
    args=parser.parse_args()
    result=inventory(json.loads(args.cargo_metadata.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    # Existing inventories are evidence, not replaceable caches.
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2,ensure_ascii=False)
        stream.write('\n')
    print(json.dumps({'components':len(result['components']),'missing_license_declarations':len(result['missing_license_declarations']),
                      'distribution_approved':False,'output':str(args.output.resolve())}))
    return 1 if args.require_distribution_approved else 0


if __name__=='__main__':
    raise SystemExit(main())
