"""Test-only source-bound Python truth; numerical evaluation needs its own window.

--check-source-only parses/hashes text and never compiles/executes extracted code.
--evaluate is separate: complete existing Python functions produce gold, not Rust.
"""
import argparse
import ast
from collections import Counter
import hashlib
import math
from pathlib import Path
import platform
import re
import struct
import sys

HERE = Path(__file__).resolve().parents[2] / 'crates/guradb-index/tests'
CASE_FILE = HERE / 'fixtures/diagnostic_cases.tsv'
BINDING_FILE = HERE / 'fixtures/source_bindings.tsv'
FUNCTIONS = {
    'fixed_layout.py': ('bounded_list', 'validate_tokens', 'tokens', 'closed', 'from_hex'),
    'fixed_bm25.py': ('materialize', 'score'),
    'fixed_vectors.py': ('materialize', 'score'),
}


def require(condition, *message):
    if not condition:
        raise ValueError(' '.join(map(str, message)) or 'invalid diagnostic input')


def source_bindings(root):
    """Bind all three production Python files and frozen Rust scoring files."""
    lines = BINDING_FILE.read_text(encoding='utf-8').splitlines()
    require(lines[0] == 'fixed-bit-sources/1', 'binding format')
    require(lines[1] == 'commit|aae4a1a4c2f69bcf5d86187bbb777da2aa6b2678', 'base reference')
    bindings, trees = [], {}
    for line in lines[2:]:
        role, relative, expected = line.split('|')
        require(role in ('python', 'candidate') and re.fullmatch('[0-9a-f]{64}', expected), 'binding shape')
        path = root / relative
        require(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()), 'binding path')
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == expected, 'source drift:', relative)
        bindings.append((role, relative, expected))
        if role == 'python':
            trees[path.name] = ast.parse(raw.decode('utf-8'), filename=relative)
    require(len(bindings) == 6 and len(trees) == 3, 'binding closure')
    return bindings, trees


def selected_nodes(name, tree):
    wanted = FUNCTIONS[name]
    definitions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    require(all(function in definitions for function in wanted), 'missing complete reference function')
    nodes = [definitions[function] for function in wanted]
    if name == 'fixed_layout.py':
        separators = [node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'SEPARATORS'
                              for target in node.targets)]
        require(len(separators) == 1, 'missing fixed separator definition')
        nodes = separators + nodes
    return nodes


def validate_score_shape(value, kind):
    # Test shim for valid diagnostic inputs only, not a public contract validator.
    require(kind == 'score' and type(value) is str and re.fullmatch('[0-9a-f]{16}', value), 'score shape')
    require(math.isfinite(struct.unpack('>d', bytes.fromhex(value))[0]), 'nonfinite input')


def namespace(name, tree, layout=None):
    environment = {'math': math, 'Counter': Counter, 'require': require,
                   'struct': struct, 'validate_shape': validate_score_shape}
    if layout is not None:
        environment.update({key: layout[key] for key in ('tokens', 'closed', 'from_hex')})
    # Compile each full AST node unchanged. No regex extraction/reassociation,
    # no Rust result, copied numeric expression, optional FMA or fallback formula.
    program = ast.Module(body=selected_nodes(name, tree), type_ignores=[])
    exec(compile(program, 'source-bound/' + name, 'exec'), environment)
    return environment


def parse_cases():
    lines = CASE_FILE.read_text(encoding='utf-8').splitlines()
    require(lines[0] == 'fixed-bit-cases/1', 'case format')
    cases, current = [], None
    for line in lines[1:]:
        fields = line.split('|')
        if fields[0] == 'case':
            require(current is None and len(fields) == 5, 'case framing')
            _, identity, kind, query, allowed = fields
            require(kind in ('exact', 'bm25'), 'case kind')
            current = {'id': identity, 'kind': kind, 'query': query,
                       'allowed': None if allowed == '*' else set(filter(None, allowed.split(','))), 'rows': []}
        elif fields[0] == 'row':
            require(current is not None and len(fields) == 5, 'row framing')
            current['rows'].append(fields[1:])
        else:
            require(fields == ['end'] and current is not None, 'case terminator')
            require(len(current['rows']) <= 100, 'source row bound')
            keys = [row[0] for row in current['rows']]
            require(len(keys) == len(set(keys)), 'duplicate diagnostic ID')
            cases.append(current)
            current = None
    expected = ['x%02d' % i for i in range(1, 13)] + ['b%02d' % i for i in range(1, 13)]
    require(current is None and [case['id'] for case in cases] == expected, 'fixed 24-case closure')
    return cases


def tokens_for(payload):
    result = []
    if payload:
        for entry in payload.split(','):
            term, count = entry.rsplit('=', 1)
            require(re.fullmatch('[1-9][0-9]*', count), 'diagnostic count')
            count = int(count)
            require(count <= 1024 and len(result) + count <= 1024, 'diagnostic token bound')
            result.extend([term] * count)
    return result


def evaluate(case, layout, bm25, exact):
    versions, rows = {}, []
    for identity, version, state, payload in case['rows']:
        require(identity and version, 'empty identity')
        versions[identity] = version
        row = {'record_id': identity, 'record_version': version}
        if case['kind'] == 'bm25':
            require(state in ('T', 'N') and (state != 'N' or bool(payload)), 'text/null state')
            row['tokens'] = tokens_for(payload) if state == 'T' else []
            layout['validate_tokens'](row['tokens'])
        else:
            require(state in ('V', 'N') and (state != 'N' or bool(payload)), 'vector/null state')
            values = payload.split(',') if state == 'V' else []
            require(state != 'V' or len(values) == 3, 'vector dimension')
            for value in values:
                layout['from_hex'](value, True)
            row.update(vector_state='present' if state == 'V' else 'null', vector_f64_hex=values)
        rows.append(row)
    if case['kind'] == 'bm25':
        documents, statistics = bm25['materialize'](rows)
        scores = bm25['score'](documents, statistics, case['query'], lambda: None)
    else:
        vectors, _ = exact['materialize'](rows)
        scores = exact['score'](vectors, case['query'].split(','), lambda: None)
    # Same fixed-reader ordering/eligibility; no candidate truncation or RRF.
    allowed = case['allowed']
    scores = [(identity, score) for identity, score in scores if allowed is None or identity in allowed]
    scores.sort(key=lambda item: (-item[1] if case['kind'] == 'bm25' else item[1], item[0]))
    return [(identity, versions[identity], struct.pack('>d', score).hex()) for identity, score in scores]


def report_sources(bindings, trees):
    print('SOURCE_ONLY; no extracted code or numerical cases evaluated')
    for role, relative, sha in bindings:
        print(role, relative, sha)
    for name, tree in trees.items():
        for node in selected_nodes(name, tree):
            syntax = ast.dump(node, include_attributes=False).encode('utf-8')
            print('complete_ast', name, getattr(node, 'name', 'SEPARATORS'), hashlib.sha256(syntax).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-source-only', action='store_true')
    mode.add_argument('--evaluate', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    bindings, trees = source_bindings(args.root)
    if args.check_source_only:
        require(args.output is None, 'source-only never writes gold')
        report_sources(bindings, trees)
        return
    require(args.output is not None, 'evaluation requires a fresh explicit artifact path')
    snapshots = {path: path.read_bytes() for path in (BINDING_FILE, CASE_FILE, Path(__file__))}
    layout = namespace('fixed_layout.py', trees['fixed_layout.py'])
    bm25 = namespace('fixed_bm25.py', trees['fixed_bm25.py'], layout)
    exact = namespace('fixed_vectors.py', trees['fixed_vectors.py'], layout)
    lines = ['fixed-bit-gold/1', 'status|COMPUTED',
             'source_bindings_hex|' + snapshots[BINDING_FILE].hex(),
             'case_inputs_hex|' + snapshots[CASE_FILE].hex(),
             'oracle_sha256|' + hashlib.sha256(snapshots[Path(__file__)]).hexdigest()]
    runtime = {'implementation': sys.implementation.name, 'version': sys.version,
               'cache_tag': sys.implementation.cache_tag, 'compiler': platform.python_compiler(),
               'system': platform.system(), 'machine': platform.machine(),
               'math_module': getattr(math, '__file__', 'built-in'),
               'mant_dig': str(sys.float_info.mant_dig), 'rounds': str(sys.float_info.rounds)}
    for key, value in runtime.items():
        lines.append('runtime|' + key + '|' + value.encode('utf-8').hex())
    for case in parse_cases():
        try:
            expected = evaluate(case, layout, bm25, exact)
        except Exception as error:
            raise RuntimeError('reference failed for ' + case['id']) from error
        lines.append('case|' + case['id'])
        lines.extend('hit|' + '|'.join(row) for row in expected)
        lines.append('end')
    # Recheck source/input identity before a result can be published as COMPUTED.
    require(source_bindings(args.root)[0] == bindings, 'source bindings changed during evaluation')
    require(all(path.read_bytes() == raw for path, raw in snapshots.items()), 'input/oracle changed during evaluation')
    # Never overwrite an earlier run/first difference or the NOT_COMPUTED template.
    require(args.output.resolve() != (HERE / 'fixtures/reference_gold.tsv').resolve(), 'not the template')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as destination:
        destination.write('\n'.join(lines) + '\n')
    print('FINITE_DIAGNOSTIC_ONLY', len(parse_cases()), args.output)


if __name__ == '__main__':
    main()
