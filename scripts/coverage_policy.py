"""Validate reviewed exclusions and account for unique executable source lines.

LLVM's LCOV LF/LH aggregate nested functions separately. DA records identify
source lines; keep both metrics instead of subtracting DA counts from LF/LH.
"""
import hashlib
import json

CATEGORIES = {'parser-invariant', 'library-invariant', 'platform-boundary', 'llvm-mapping'}


def read_lcov(path, sources):
    files = {}
    current = None
    for row in path.read_text().splitlines():
        if row.startswith('SF:'):
            name = row[3:]
            current = name.removeprefix('/workspace/')
            if current not in sources:
                raise ValueError(f'unexpected coverage source: {name}')
            if current in files:
                raise ValueError(f'duplicate coverage source: {name}')
            files[current] = {}
        elif row.startswith('DA:'):
            if current is None:
                raise ValueError('line record outside source')
            line, count = map(int, row[3:].split(',')[:2])
            if line < 1 or count < 0 or line in files[current]:
                raise ValueError(f'invalid/duplicate coverage line: {current}:{line}')
            files[current][line] = count
        elif row == 'end_of_record':
            current = None
    if current is not None or not sources or set(files) != sources or any(not lines for lines in files.values()):
        raise ValueError(f'missing/empty coverage source: {sorted(sources-set(files))}')
    return files


def exclusions(root, files, path):
    manifest = json.loads(path.read_text())
    if (set(manifest) != {'schema_version', 'rust'}
            or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1):
        raise ValueError('unsupported coverage exclusion schema')
    excluded = {name: set() for name in files}
    for item in manifest['rust']:
        if set(item) != {'path', 'source_sha256', 'category', 'reason', 'evidence', 'lines'}:
            raise ValueError('incomplete coverage exclusion')
        name = item['path']
        if name not in files or item['category'] not in CATEGORIES:
            raise ValueError(f'invalid exclusion path/category: {name}')
        if any(not isinstance(item[key], str) or not item[key].strip() for key in ('reason', 'evidence')):
            raise ValueError(f'exclusion requires reason and evidence: {name}')
        source = (root/name).read_bytes()
        if hashlib.sha256(source).hexdigest() != item['source_sha256']:
            raise ValueError(f'stale coverage exclusion: {name}')
        source_lines = source.decode().splitlines()
        if not isinstance(item['lines'], list) or not item['lines']:
            raise ValueError(f'empty exclusion: {name}')
        for entry in item['lines']:
            if set(entry) != {'number', 'text'}:
                raise ValueError('exclusions require individual line and exact text')
            line = entry['number']
            if (type(line) is not int or line not in files[name] or line > len(source_lines)
                    or source_lines[line-1] != entry['text'] or line in excluded[name]):
                raise ValueError(f'invalid/stale/duplicate exclusion line: {name}:{line}')
            if item['category'] == 'llvm-mapping' and entry['text'].strip() not in {'}', ')?;'}:
                raise ValueError(f'LLVM mapping exemption must be delimiter only: {name}:{line}')
            excluded[name].add(line)
    if any(len(excluded[name]) == len(lines) for name, lines in files.items()):
        raise ValueError('whole-source exclusion is prohibited')
    return excluded


def summarize(root, files, manifest):
    excluded = exclusions(root, files, manifest)
    result = {}
    for name, lines in sorted(files.items()):
        missed = {line for line, count in lines.items() if count == 0}
        exempt = excluded[name]
        result[name] = {
            'raw_lines': len(lines), 'raw_covered': len(lines)-len(missed),
            'excluded_lines': sorted(exempt), 'excluded_covered': len(exempt-missed),
            'eligible_lines': len(lines)-len(exempt),
            'eligible_covered': len(lines)-len(missed | exempt),
            'missing_lines': sorted(missed-exempt),
        }
    totals = {key: sum(item[key] for item in result.values()) for key in
              ('raw_lines', 'raw_covered', 'excluded_covered', 'eligible_lines', 'eligible_covered')}
    totals['excluded_lines'] = sum(len(item['excluded_lines']) for item in result.values())
    totals['missing_lines'] = sum(len(item['missing_lines']) for item in result.values())
    return {'metric': 'lcov-unique-source-lines', 'files': result, 'totals': totals}
