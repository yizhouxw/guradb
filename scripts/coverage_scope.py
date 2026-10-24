"""Complete owner coverage scopes; defaults retain the original whole product."""
from coverage_policy import THRESHOLDS
from pathlib import Path
import re

from harnesslib.policy import HarnessError, load
from harnesslib.validation_registry import digest, load_registry, source_inventory


def coverage_scope(root, modules):
    policy, architecture, *_ = load(root)
    registry = load_registry(root, policy, architecture)
    modules = sorted(modules)
    if len(modules) != len(set(modules)) or not modules or set(modules) - set(architecture["modules"]):
        raise HarnessError("coverage modules must be unique known owners")
    if any(registry["modules"][name]["state"] != "ready" for name in modules):
        raise HarnessError("module coverage requires an executable real component mapping")
    inventory = source_inventory(root, policy, architecture, modules)
    python = [name for name in inventory if name.endswith(".py")]
    rust = [name for name in inventory if name.endswith(".rs")]
    packages = [registry["modules"][name]["package"] for name in modules]
    if not python or not rust:
        raise HarnessError("mapped coverage profile must retain both owner languages")
    tests = sorted({path for name in modules for path in registry["modules"][name]["python_tests"]})
    value = {"modules": modules, "sources": inventory, "python_sources": python, "rust_sources": rust,
             "packages": packages, "python_tests": tests, "threshold_percent": dict(THRESHOLDS),
             "registry_sha256": digest(registry), "architecture_sha256": digest(architecture),
             "python_fixture_scope": "legacy unit/contract closure; denominator remains complete owner"}
    value["sha256"] = digest(value)
    return value


def package_args(scope):
    return [arg for package in scope["packages"] for arg in ("--package", package)] if scope else ["--workspace"]


def ignore_regex(root, scope):
    """Exclude other owners from report, never any selected source or test cost."""
    if not scope:
        return "(^|/)tests/"
    selected = {Path(name).parts[1] for name in scope["rust_sources"]}
    other = sorted(path.name for path in (root / "crates").iterdir() if path.is_dir() and path.name not in selected)
    return "(^|/)tests/" + ("|(^|/)crates/(" + "|".join(re.escape(name) for name in other) + ")/" if other else "")


def python_roots(root, scope):
    if not scope:
        return None
    return sorted({str(root / Path(name).parent) for name in scope["python_sources"]})


def production_sources(root):
    policy, architecture, *_ = load(root)
    return source_inventory(root, policy, architecture, sorted(architecture["modules"]))
