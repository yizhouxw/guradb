"""Strict validation registry: component readiness is explicit, never inferred."""
import hashlib
import json
from pathlib import Path
import os
import re
import tomllib

from .policy import HarnessError, git, normalize_path, owner, read_toml


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def load_registry(root, policy, architecture):
    value = read_toml(root / "harness/validation.toml")
    expected = {"schema_version", "engineering_prefixes", "engineering_paths", "system_prefixes",
                "system_paths", "modules", "components", "pairs"}
    if (set(value) - {"candidate_closure"} != expected
            or set(value["modules"]) != set(architecture["modules"])):
        raise HarnessError("validation registry must cover every architecture owner and no unknown fields")
    if "candidate_closure" in value:
        validate_candidate(value["candidate_closure"], architecture)
    for key in ("engineering_prefixes", "engineering_paths", "system_prefixes", "system_paths"):
        entries = value[key]
        if not isinstance(entries, list) or len(entries) != len(set(entries)):
            raise HarnessError(f"invalid validation registry {key}")
        for entry in entries:
            if not isinstance(entry, str) or normalize_path(entry) != entry.rstrip("/"):
                raise HarnessError(f"invalid validation path: {entry}")
            if key.endswith("prefixes") and not entry.endswith("/"):
                raise HarnessError("validation prefixes require trailing slash")
    for name, component in value["components"].items():
        keys = {"modules", "boundary"} | {part + suffix for part in ("functional", "performance", "fault")
                                        for suffix in ("_suite", "_index")}
        if (set(component) != keys or not isinstance(component["boundary"], str)
                or not component["boundary"].strip() or not component["modules"]
                or set(component["modules"]) - set(architecture["modules"])):
            raise HarnessError(f"invalid component {name}")
        for part in ("functional", "performance", "fault"):
            suite = policy["suites"].get(component[part + "_suite"], {})
            index = component[part + "_index"]
            if (suite.get("state") != "ready" or type(index) is not int
                    or not 0 <= index < len(suite["commands"])):
                raise HarnessError(f"{name}: real {part} command is not ready")
    for name, module in value["modules"].items():
        if module.get("state") == "pending":
            if set(module) != {"state", "reason"} or not module["reason"].strip():
                raise HarnessError(f"{name}: pending module needs reason")
            continue
        if (set(module) != {"state", "reason", "change_suffixes", "package", "component", "python_tests"}
                or module["state"] != "ready" or not module["reason"].strip()
                or module["component"] not in value["components"]
                or name not in value["components"][module["component"]]["modules"]
                or not module["change_suffixes"] or set(module["change_suffixes"]) - {".rs", ".py"}):
            raise HarnessError(f"{name}: invalid ready module profile")
        manifests = [root / prefix / "Cargo.toml" for prefix in architecture["modules"][name]["paths"]
                     if prefix.startswith("crates/")]
        if len(manifests) != 1 or not manifests[0].is_file():
            raise HarnessError(f"{name}: missing real Cargo package")
        with manifests[0].open("rb") as stream:
            actual = tomllib.load(stream)["package"]["name"]
        if module["package"] != actual:
            raise HarnessError(f"{name}: Cargo package mapping does not match manifest")
        if not module["python_tests"]:
            raise HarnessError(f"{name}: no real Python unit fixture closure")
        for path in module["python_tests"]:
            if normalize_path(path) != path or not path.startswith("tests/") or not (root/path).is_dir():
                raise HarnessError(f"{name}: invalid Python test closure")
    for name, pair in value["pairs"].items():
        if (set(pair) != {"modules", "component"} or len(pair["modules"]) != 2
                or len(set(pair["modules"])) != 2 or pair["component"] not in value["components"]
                or any(value["modules"].get(module, {}).get("state") != "ready" for module in pair["modules"])
                or set(pair["modules"]) - set(value["components"][pair["component"]]["modules"])):
            raise HarnessError(f"{name}: invalid real paired closure")
    return value


def _strings(value, label, allow_empty=False):
    if (not isinstance(value, list) or not allow_empty and not value
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(value) != len(set(value))):
        raise HarnessError(f"candidate closure: invalid {label}")
    return value


def validate_candidate(candidate, architecture):
    """Validate declarative tool candidates, never grant an executable route."""
    if (not isinstance(candidate, dict)
            or set(candidate) != {"mode", "contract", "qa_source", "methods"}
            or candidate["mode"] != "candidate"):
        raise HarnessError("candidate closure cannot assert active qualification")
    contract = candidate["contract"]
    if (not isinstance(contract, dict) or set(contract) != {"version", "canonical_sha256"}
            or not isinstance(contract["version"], str) or not contract["version"].strip()
            or not isinstance(contract["canonical_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", contract["canonical_sha256"])
            or not isinstance(candidate["qa_source"], str) or not candidate["qa_source"].strip()
            or not isinstance(candidate["methods"], list) or not candidate["methods"]):
        raise HarnessError("candidate closure needs an exact contract and QA source")
    methods, graph = set(), {}
    for method in candidate["methods"]:
        if (not isinstance(method, dict) or set(method) != {"id", "owner", "consumers", "trigger_paths",
                "contract", "observations", "driver_profile"}
                or not isinstance(method["id"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", method["id"])
                or method["id"] in methods or method["contract"] != contract
                or not isinstance(method["owner"], str) or method["owner"] not in architecture["modules"]):
            raise HarnessError("candidate closure has a conflicting method/contract/owner")
        methods.add(method["id"])
        producer = method["owner"]
        consumers = _strings(method["consumers"], "consumers", allow_empty=True)
        for consumer in consumers:
            if (consumer not in architecture["modules"] or consumer == producer
                    or producer not in architecture["modules"][consumer]["allowed"]):
                raise HarnessError("candidate closure has an unknown or forbidden consumer edge")
        graph.setdefault(producer, set()).update(consumers)
        for path in _strings(method["trigger_paths"], "trigger paths"):
            if normalize_path(path) != path or owner(path, architecture) != producer:
                raise HarnessError("candidate closure has a conflicting/noncanonical trigger")
        _strings(method["observations"], "observations")
        driver = method["driver_profile"]
        if (not isinstance(driver, dict) or set(driver) != {"id", "state", "reason"}
                or not isinstance(driver["id"], str) or not driver["id"].strip()
                or not isinstance(driver["state"], str) or driver["state"] not in {"pending", "unregistered"}
                or not isinstance(driver["reason"], str) or not driver["reason"].strip()):
            raise HarnessError("candidate driver/profile remains pending or unregistered, never ready")
    visiting, visited = set(), set()

    def visit(node):
        if node in visiting:
            raise HarnessError("candidate consumer graph contains a cycle")
        if node in visited:
            return
        visiting.add(node)
        for consumer in sorted(graph.get(node, ())):
            visit(consumer)
        visiting.remove(node)
        visited.add(node)

    for producer in sorted(graph):
        visit(producer)


def required_closure(paths, registry, architecture):
    """Method impact evidence is separate from the selected executable profile."""
    base = {"mode": "unregistered", "contract": None, "qa_source": None, "methods": None,
            "trigger_paths": sorted(paths), "required_owners": None, "required_consumers": None,
            "method_bindings": None, "driver_profiles": None,
            "unresolved": [{"reason": "registry_not_connected"}]}
    candidate = registry.get("candidate_closure")
    if candidate is None:
        return base
    validate_candidate(candidate, architecture)
    selected, consumers = {}, set()
    for method in candidate["methods"]:
        if set(paths) & set(method["trigger_paths"]):
            selected[method["id"]] = method
            consumers.update(method["consumers"])
    while True:
        added = [method for method in candidate["methods"]
                 if method["owner"] in consumers and method["id"] not in selected]
        if not added:
            break
        for method in added:
            selected[method["id"]] = method
            consumers.update(method["consumers"])
    declared = {path for method in candidate["methods"] for path in method["trigger_paths"]}
    unknown = sorted(path for path in paths if path not in declared and Path(path).suffix not in {".md", ".rst"})
    ordered = [selected[name] for name in sorted(selected)]
    unresolved = [{"method": method["id"], "reason": method["driver_profile"]["reason"],
                   "state": method["driver_profile"]["state"]} for method in ordered]
    unresolved.extend({"owner": consumer, "reason": "consumer_method_unregistered"}
                      for consumer in sorted(consumers - {method["owner"] for method in ordered}))
    if unknown:
        unresolved.append({"reason": "unmapped_trigger", "paths": unknown})
    return {**base, "mode": "candidate", "contract": candidate["contract"], "qa_source": candidate["qa_source"],
            "methods": sorted(selected) if not unknown else None,
            "required_owners": sorted({method["owner"] for method in ordered} | consumers) if not unknown else None,
            "required_consumers": sorted(consumers) if not unknown else None,
            "method_bindings": [{key: method[key] for key in ("id", "owner", "consumers", "trigger_paths", "observations")}
                                for method in ordered],
            "driver_profiles": [{"method": method["id"], **method["driver_profile"]} for method in ordered],
            "unresolved": unresolved}


def _runtime_path(path):
    parts = Path(path).parts
    if path.startswith(("modules/", "clients/")):
        return path.endswith(".py")
    if len(parts) < 3 or parts[0] != "crates" or not path.endswith(".rs"):
        return False
    # These are Cargo's explicit test/example/bench/build targets, not runtime.
    # All other owned Rust layouts count, including #[path] outside src/.
    return parts[2] not in {"tests", "examples", "benches", "build.rs"}


def _check_rust_paths(root, inventory, architecture):
    crate_roots = {Path(name).parts[1] for name in inventory if name.startswith("crates/")}
    for crate in crate_roots:
        manifest = root/"crates"/crate/"Cargo.toml"
        if not manifest.is_file():
            continue  # Inventory-only fixtures; ready profiles independently require manifests.
        with manifest.open("rb") as stream:
            package = tomllib.load(stream)
        targets = [package.get("lib", {})] + package.get("bin", [])
        for target in targets:
            if "path" not in target:
                continue
            value = target["path"]
            if not isinstance(value, str):
                raise HarnessError("Cargo target path must be a repository-owned source")
            resolved = (manifest.parent/value).resolve()
            if (not resolved.is_relative_to(root)
                    or resolved.relative_to(root).as_posix() not in inventory
                    or not resolved.is_relative_to(manifest.parent)):
                raise HarnessError(f"Cargo runtime target outside inventoried owner: {manifest.relative_to(root)}")
    for relative in inventory:
        if not relative.endswith(".rs"):
            continue
        text = (root/relative).read_text()
        if re.search(r"\binclude!\s*\(", text) or re.search(r"cfg_attr\([^]]*\bpath\s*=", text):
            raise HarnessError(f"uncertified generated/conditional Rust layout: {relative}")
        matches = list(re.finditer(r'#\[\s*path\s*=\s*"([^"\\]+)"\s*\]', text))
        if len(matches) != len(re.findall(r"#\[\s*path\b", text)):
            raise HarnessError(f"uncertified Rust path attribute: {relative}")
        for match in matches:
            # The baseline unit fixtures use this exact adjacent cfg(test).
            before = text[:match.start()].rstrip()
            if before.endswith("#[cfg(test)]"):
                continue
            target = (root/relative).parent.joinpath(match[1]).resolve()
            if (not target.is_relative_to(root.resolve())
                    or target.relative_to(root.resolve()).as_posix() not in inventory):
                raise HarnessError(f"Rust runtime path outside inventoried closure: {relative}")
            if owner(target.relative_to(root.resolve()).as_posix(), architecture) != owner(relative, architecture):
                raise HarnessError(f"Rust runtime path crosses source owner: {relative}")


def source_inventory(root, policy, architecture, modules):
    """Git plus disk closure: never discard an owned nested build/ directory."""
    root = root.resolve()
    raw = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    candidates = {normalize_path(value.decode()) for value in raw.split(b"\0") if value}
    # Ignored runtime source is not a license to omit imports. Check owner roots
    # independently; normal ignored __pycache__/*.pyc adds no runtime source.
    for module in modules:
        for prefix in architecture["modules"][module]["paths"]:
            for directory, subdirectories, names in os.walk(root/prefix, followlinks=False):
                for child in subdirectories + names:
                    path = Path(directory)/child
                    if path.is_symlink():
                        raise HarnessError(f"owned source cannot be a symlink: {path.relative_to(root)}")
                for name in names:
                    relative = (Path(directory)/name).relative_to(root).as_posix()
                    if _runtime_path(relative) and relative not in candidates:
                        raise HarnessError(f"ignored runtime source cannot be certified: {relative}")
    result = {}
    for relative in sorted(candidates):
        path = root/relative
        # A tracked deletion is still an impact input, but has no current
        # production denominator. A retired owner may therefore disappear.
        # Existing/untracked sources still require exactly one live owner.
        if not path.exists() and not path.is_symlink():
            continue
        module = owner(relative, architecture)
        suffix = Path(relative).suffix
        if module in modules and suffix in policy["source_extensions"] and suffix not in {".py", ".rs"}:
            raise HarnessError(f"production coverage language has no certified scope: {relative}")
        if _runtime_path(relative) and module is None:
            raise HarnessError(f"unowned production source cannot be certified: {relative}")
        if not _runtime_path(relative) or owner(relative, architecture) not in modules:
            continue
        if path.is_symlink():
            raise HarnessError(f"coverage source cannot be a symlink: {relative}")
        if path.exists():  # tracked deletion is absent, but both rename sides still select risk.
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    for module in modules:
        if not any(owner(path, architecture) == module for path in result):
            raise HarnessError(f"empty production source denominator: {module}")
    _check_rust_paths(root, result, architecture)
    return result
