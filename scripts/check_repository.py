#!/usr/bin/env python3
"""Check the current alpha contract and retirement, not historical demo docs."""
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCS = ('README.md', 'AGENTS.md', 'CONTRIBUTING.md', 'docs/README.md', 'docs/user/README.md', 'docs/user/simple-alpha.md',
                'docs/decisions/0028-simple-rust-alpha.md', 'docs/design/simple-alpha-plan.md',
                'harness/README.md', 'harness/validation-strategy.md', 'tests/README.md', 'api/README.md',
                'examples/README.md')
LINK = re.compile(r'!?\[[^\]\n]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+"[^\"]*")?\s*\)')


def check_links(path):
    errors = []
    text = re.sub(r'(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1\s*$', '', path.read_text())
    for match in LINK.finditer(text):
        target = match.group(1) or match.group(2)
        url = urlsplit(target)
        if url.scheme or url.netloc or not url.path:
            continue
        destination = (path.parent/unquote(url.path)).resolve()
        if not destination.is_relative_to(ROOT) or not destination.exists():
            errors.append(f'{path.relative_to(ROOT)}: invalid local link: {target}')
    return errors


def main():
    from harnesslib.stages import retirement
    errors = []
    for name in CURRENT_DOCS:
        path = ROOT/name
        if not path.is_file() or path.is_symlink():
            errors.append('missing/invalid current document: '+name)
        else:
            errors.extend(check_links(path))
    retired = retirement(ROOT)
    capabilities = json.loads((ROOT/'api/capabilities/v1.json').read_text())
    if capabilities.get('product') != 'simple-rust-alpha' or capabilities.get('execution') != 'Rust only, local single-process':
        errors.append('current capability registration must describe only Rust CLI alpha')
    if not (ROOT/'crates/guradb/Cargo.toml').is_file():
        errors.append('current Rust crate missing')
    if any((ROOT/'modules').rglob('*.py')) or any((ROOT/'clients').rglob('*.py')):
        errors.append('retired Python online modules remain')
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'OK: {len(CURRENT_DOCS)} current alpha documents, CLI capabilities, {len(retired)} retired paths absent. Historical design documents are outside the current operational contract.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
