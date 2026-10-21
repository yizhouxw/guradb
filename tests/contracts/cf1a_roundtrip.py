"""Real Python -> Rust -> Python and Rust -> Python -> Rust wire exchange.

Build the example first, then pass its executable command after --. This driver
fails on a missing executable and never substitutes a Python implementation.
"""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from modules.common.cf1a_wire import canonical, decode, digest


def exchange(command):
    golden = json.loads((ROOT/'api/cf1a/golden.json').read_text())
    for value in golden:
        python = decode(canonical(value))
        rust = subprocess.run(command, input=python.encoded, capture_output=True, check=True).stdout
        assert decode(rust).encoded == python.encoded
        # Start with noncanonical Rust input to prove both directions normalize.
        rust_first = subprocess.run(command, input=json.dumps(value, ensure_ascii=True, indent=2).encode(),
                                    capture_output=True, check=True).stdout
        python_second = decode(rust_first)
        rust_again = subprocess.run(command, input=python_second.encoded, capture_output=True, check=True).stdout
        assert rust_first == python_second.encoded == rust_again == python.encoded
    negative = json.loads((ROOT/'api/cf1a/rejections.json').read_text())
    for case in negative:
        raw = case['raw'].encode()
        try:
            decode(raw)
        except ValueError as error:
            assert error.code == case['code'], (case['name'], error.code)
        else:
            raise AssertionError('Python accepted '+case['name'])
        result = subprocess.run(command, input=raw, capture_output=True, check=False)
        assert result.returncode != 0, 'Rust accepted '+case['name']
        assert result.stderr.decode().split(':',1)[0] == case['code'], (case['name'], result.stderr)
    return {'golden_count': len(golden), 'rejection_count': len(negative),
            'golden_sha256': digest(golden), 'directions': ['python-rust-python', 'rust-python-rust']}


if __name__ == '__main__':
    if len(sys.argv) < 3 or sys.argv[1] != '--':
        raise SystemExit('Pass the already built Rust example command after --')
    print(json.dumps(exchange(sys.argv[2:]), sort_keys=True))
