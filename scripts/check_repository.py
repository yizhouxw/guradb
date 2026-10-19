#!/usr/bin/env python3
"""Offline repository checks; not a full Markdown or OpenAPI validator."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {".git", ".venv", "node_modules", "target", "build", "dist", "__pycache__"}
LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+\"[^\"]*\")?\s*\)")
METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def repository_files() -> list[Path]:
    files = []
    for directory, subdirectories, names in os.walk(ROOT):
        subdirectories[:] = [name for name in subdirectories if name not in IGNORED
                             and not (Path(directory) == ROOT and name in {"artifacts", "data", "tmp"})]
        files.extend(Path(directory) / name for name in names)
    return sorted(files)


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"),
                      object_pairs_hook=unique_object, parse_constant=reject_constant)


def resolve_ref(document: dict, reference: str) -> object:
    if not reference.startswith("#/"):
        raise ValueError(f"only local JSON Pointer refs are allowed: {reference}")
    current = document
    for token in reference[2:].split("/"):
        token = unquote(token).replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def inspect_refs(value: object, document: dict) -> None:
    if isinstance(value, dict):
        if "$ref" in value:
            resolve_ref(document, value["$ref"])
        for child in value.values():
            inspect_refs(child, document)
    elif isinstance(value, list):
        for child in value:
            inspect_refs(child, document)


def check_openapi(document: dict) -> int:
    if not document.get("openapi", "").startswith("3.1."):
        raise ValueError("expected OpenAPI 3.1.x")
    if not document.get("info", {}).get("version") or not document.get("paths"):
        raise ValueError("missing API version or paths")
    inspect_refs(document, document)
    identifiers = set()
    for route, item in document["paths"].items():
        if not route.startswith("/"):
            raise ValueError(f"invalid API path: {route}")
        for method, operation in item.items():
            if method not in METHODS:
                continue
            identifier = operation.get("operationId")
            if not identifier or identifier in identifiers:
                raise ValueError(f"missing or duplicate operationId: {identifier}")
            identifiers.add(identifier)
            if not operation.get("responses"):
                raise ValueError(f"missing responses: {identifier}")
            parameters = item.get("parameters", []) + operation.get("parameters", [])
            resolved = [resolve_ref(document, p["$ref"]) if "$ref" in p else p for p in parameters]
            for name in re.findall(r"\{([^{}]+)\}", route):
                if not any(p.get("name") == name and p.get("in") == "path"
                           and p.get("required") is True for p in resolved):
                    raise ValueError(f"missing required path parameter: {route}: {name}")
    return len(identifiers)


def check_links(path: Path) -> list[str]:
    errors = []
    text = path.read_text(encoding="utf-8")
    # All repository examples use fenced blocks; links inside them are illustrative.
    text = re.sub(r"(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1\s*$", "", text)
    for match in LINK.finditer(text):
        target = match.group(1) or match.group(2)
        url = urlsplit(target)
        if url.scheme or url.netloc or not url.path:
            continue
        destination = (path.parent / unquote(url.path)).resolve()
        if not destination.is_relative_to(ROOT):
            errors.append(f"{path.relative_to(ROOT)}: link leaves repository: {target}")
        elif not destination.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing link target: {target}")
    return errors


def main() -> int:
    errors = []
    required = [
        "README.md", "AGENTS.md", "CONTRIBUTING.md", "Makefile",
        "docs/README.md", "docs/vision.md", "docs/architecture.md", "docs/roadmap.md",
        "docs/decisions/README.md", "docs/compatibility/lake-formats.md",
        "docs/interfaces/query-and-clients.md", "api/http/openapi.json", "tests/README.md",
        "docs/research/README.md", "docs/product/functional-architecture.md",
        "docs/research/ai-data-and-retrieval.md", "docs/research/execution-and-ecosystem.md",
        "docs/research/lake-storage.md", "docs/research/search-and-graph.md",
        "docs/decisions/0002-object-store-lake-boundary.md",
        "docs/decisions/0003-storage-and-execution-baseline.md",
        "docs/decisions/0004-snapshot-and-index-publication.md",
        "docs/decisions/0005-agent-harness-and-quality-gates.md",
        "harness/README.md", "harness/policy.toml", "harness/architecture.toml",
        "harness/invariants.toml", "harness/workloads.toml", "harness/faults.toml",
        "harness/quality-model.md", "harness/evidence.md", "harness/runtime-onboarding.md",
        "scripts/harness.py", "requirements-dev.txt", "requirements-dev.lock",
        "tests/contracts/test_http_contract.py", "tests/harness/test_policy.py",
        "tests/harness/test_architecture.py", "tests/harness/test_evidence.py", "tests/harness/test_runner.py",
        "tests/harness/test_dependencies.py",
        "harness/version-control.md", "scripts/harnesslib/version_control.py",
        "tests/harness/test_version_control.py", ".githooks/pre-commit",
        "docs/decisions/0008-git-traceability-and-recovery.md",
        "harness/development-workflow.md", "harness/ci-cd.md",
        "scripts/harnesslib/task_state.py", "scripts/harnesslib/workflow.py",
        "scripts/harnesslib/check_evidence.py", "tests/harness/test_workflow.py",
        "tests/harness/test_ci_workflow.py", "docs/decisions/0009-task-evidence-and-actions-workflow.md",
    ]
    required += [f"docs/user/{name}.md" for name in
                 ("README", "features", "architecture", "installation", "usage",
                  "operations", "development", "diagnostics", "validation")]
    required += ["harness/templates/user-scenario.md",
                 "docs/decisions/0016-user-documentation-first.md"]
    required += [f"modules/{name}/README.md" for name in
                 ("gateway", "query", "catalog", "storage", "index", "cluster", "connectors")]
    required += [f"clients/{name}/README.md" for name in ("cli", "mcp")]
    for relative in required:
        if not (ROOT / relative).is_file():
            errors.append(f"missing required file: {relative}")
    files = repository_files()
    markdown = [path for path in files if path.suffix == ".md"]
    json_files = [path for path in files if path.suffix == ".json"]
    for path in markdown:
        errors.extend(check_links(path))
    documents = {}
    for path in json_files:
        try:
            documents[path] = load_json(path)
        except (ValueError, OSError) as error:
            errors.append(f"{path.relative_to(ROOT)}: {error}")
    operations = 0
    api_path = ROOT / "api/http/openapi.json"
    if api_path in documents:
        try:
            operations = check_openapi(documents[api_path])
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
            errors.append(f"api/http/openapi.json: {error}")
    if errors:
        for error in errors:
            print(f"ERROR {error}", file=sys.stderr)
        return 1
    print(f"OK: {len(markdown)} Markdown files, {len(json_files)} JSON files, "
          f"{operations} API operations; local links and basic contract checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
