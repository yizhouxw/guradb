"""Check declared module edges and real local Cargo dependencies without Rust."""

from __future__ import annotations

from pathlib import Path
import tomllib

from .policy import HarnessError, files, owner, production_source


def cycles(graph: dict[str, set[str]]) -> None:
    visiting, visited = set(), set()

    def visit(node: str) -> None:
        if node in visiting:
            raise HarnessError(f"dependency cycle at {node}")
        if node in visited:
            return
        visiting.add(node)
        for dependency in sorted(graph[node]):
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node)


def dependency_tables(document: dict) -> list[dict]:
    tables = [document]
    tables.extend(document.get("target", {}).values())
    return [table[key] for table in tables
            for key in ("dependencies", "dev-dependencies", "build-dependencies") if key in table]


def lint(root: Path, policy: dict, architecture: dict) -> list[str]:
    root = root.resolve()
    paths = files(root, set(policy["ignored_directories"]))
    modules = architecture["modules"]
    cycles({name: set(module["allowed"]) for name, module in modules.items()})
    manifests = {}
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise HarnessError(f"symlink file is outside the checked ownership model: {relative}")
        if path.suffix in policy["source_extensions"]:
            if len(path.read_text(encoding="utf-8").splitlines()) > policy["max_source_lines"]:
                raise HarnessError(f"{relative}: source exceeds {policy['max_source_lines']} lines; split responsibilities")
            if production_source(relative, policy) and not owner(relative, architecture):
                raise HarnessError(f"unowned production source: {relative}")
        if path.name == "Cargo.toml":
            with path.open("rb") as stream:
                manifests[path.resolve()] = tomllib.load(stream)
    workspace = manifests.get((root / "Cargo.toml").resolve(), {}).get("workspace", {})
    inherited = workspace.get("dependencies", {})
    graph = {}
    for path, document in manifests.items():
        if "package" not in document:
            continue
        relative = path.relative_to(root).as_posix()
        source_module = owner(relative, architecture)
        if not source_module:
            raise HarnessError(f"unowned Cargo package: {relative}")
        graph[path] = set()
        for table in dependency_tables(document):
            for alias, specification in table.items():
                base = path.parent
                if isinstance(specification, dict) and specification.get("workspace") is True:
                    if alias not in inherited:
                        raise HarnessError(f"{relative}: unknown workspace dependency {alias}")
                    specification, base = inherited[alias], root
                if not isinstance(specification, dict) or "path" not in specification:
                    continue
                target = (base / specification["path"] / "Cargo.toml").resolve()
                if not target.is_relative_to(root):
                    raise HarnessError(f"{relative}: local dependency escapes repository")
                if target not in manifests or "package" not in manifests[target]:
                    raise HarnessError(f"{relative}: unresolved local dependency {alias}")
                target_module = owner(target.relative_to(root).as_posix(), architecture)
                if target_module != source_module and target_module not in modules[source_module]["allowed"]:
                    raise HarnessError(f"forbidden module dependency: {source_module} -> {target_module}")
                graph[path].add(target)
    cycles(graph)
    from .python_architecture import check as check_python
    python_summary = check_python(root, paths, policy, architecture, cycles)
    return [python_summary, f"module DAG and {len(graph)} Cargo packages checked",
            "Cargo edges include normal/build/dev/target and workspace inheritance",
            "Rust imports, remote dependency behavior and runtime invariants still need compiler/tests"]
