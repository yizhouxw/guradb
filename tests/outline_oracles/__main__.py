"""Reproduce the frozen P01 source truth and clearly scoped evidence summary."""
import json

from .truth import OutlineOracle


def main():
    summary = OutlineOracle().verify_golden()
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
