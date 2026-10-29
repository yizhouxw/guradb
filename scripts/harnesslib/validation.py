"""Closed change selection and level-bound execution profiles (report schema 2)."""
if __package__ == "scripts.harnesslib":
    from ..coverage_policy import THRESHOLDS
else:
    from coverage_policy import THRESHOLDS
from pathlib import PurePosixPath

from .policy import HarnessError, normalize_path, owner, plan as legacy_plan
from .validation_registry import digest, load_registry, required_closure, source_inventory
from .stages import core_suites, documentation_path, stage_options

LEVELS = ("auto", "module", "pair", "system", "release")


def _matches(path, registry, kind):
    return path in registry[kind + "_paths"] or path.startswith(tuple(registry[kind + "_prefixes"]))


def classify(paths, registry, architecture):
    affected, reasons, engineering = set(), [], False
    for path in paths:
        if PurePosixPath(path).suffix in {".md", ".rst"}:
            continue
        if path.endswith("/build.rs"):
            reasons.append(f"{path}: Cargo build script requires system compilation; not runtime coverage")
        elif _matches(path, registry, "system"):
            reasons.append(f"{path}: shared contract/dependency requires system")
        elif _matches(path, registry, "engineering"):
            engineering = True
        else:
            module = owner(path, architecture)
            if module is None:
                reasons.append(f"{path}: unknown validation owner/mapping; system fallback")
                continue
            affected.add(module)
            mapping = registry["modules"][module]
            if mapping["state"] != "ready":
                reasons.append(f"{path}: {module}: {mapping['reason']}")
            elif PurePosixPath(path).suffix not in mapping["change_suffixes"]:
                reasons.append(f"{path}: {module}: language/component profile not mapped")
    if reasons:
        return "system", sorted(affected), None, reasons
    if engineering and affected:
        return "system", sorted(affected), None, ["engineering and product change requires system"]
    if engineering:
        return "engineering", [], None, ["engineering selftests, selector evidence and native query regression"]
    if not affected:
        return "documentation", [], None, ["documentation only; no product quality assertion"]
    if len(affected) == 1:
        return "module", sorted(affected), None, []
    for name, pair in registry["pairs"].items():
        if affected == set(pair["modules"]):
            return "pair", sorted(affected), name, []
    return "system", sorted(affected), None, ["changed owners have no registered real paired closure"]


def _scoped_suites(policy, registry, modules, pair):
    suites = {name: policy["suites"][name] for name in policy["bootstrap_suites"]}
    packages = [registry["modules"][name]["package"] for name in modules]
    package_args = [item for name in packages for item in ("--package", name)]
    suites["module-rust"] = {"state": "ready", "timeout_seconds": policy["suites"]["rust"]["timeout_seconds"],
        "commands": [["{python}", "scripts/cargo.py", "fmt", *package_args, "--", "--check"],
                     ["{python}", "scripts/cargo.py", "clippy", *package_args, "--all-targets", "--locked", "--", "-D", "warnings"],
                     ["{python}", "scripts/cargo.py", "test", *package_args, "--locked"]]}
    suites["module-unit-coverage"] = {"state": "ready", "timeout_seconds": policy["suites"]["unit-coverage"]["timeout_seconds"],
        "commands": [["{python}", "scripts/unit_coverage.py", "--language", "all", "--run-dir", "{run_dir}/module-coverage",
                      *[item for name in modules for item in ("--module", name)]]]}
    component_name = registry["pairs"][pair]["component"] if pair else registry["modules"][modules[0]]["component"]
    component = registry["components"][component_name]
    for part in ("functional", "performance", "fault"):
        original = policy["suites"][component[part + "_suite"]]
        suites["component-" + part] = {"state": original["state"], "timeout_seconds": original["timeout_seconds"],
                                      "commands": [original["commands"][component[part + "_index"]]]}
    return suites, {component_name: component}


def validation_plan(root, paths, policy, architecture, invariants, level="auto", modules=(), scope="change",
                    stage="hardening", core_flow=None):
    stage_options(stage, core_flow)
    if level not in LEVELS or scope not in {"change", "release", "bootstrap"}:
        raise HarnessError("invalid validation level/scope")
    paths = sorted({normalize_path(path) for path in paths})
    registry = load_registry(root, policy, architecture)
    minimum, affected, pair, reasons = classify(paths, registry, architecture)
    required = required_closure(paths, registry, architecture)
    if required["mode"] == "candidate" and required["unresolved"]:
        if level in {"module", "pair"}:
            raise HarnessError("candidate pending/unknown closure cannot qualify module/pair execution")
        # An unresolved candidate is never permission to run a narrower profile.
        if minimum not in {"engineering", "documentation"}:
            minimum, pair = "system", None
            reasons = [*reasons, "candidate closure unresolved; system does not certify its drivers"]
    modules = list(modules)
    if len(modules) != len(set(modules)) or set(modules) - set(registry["modules"]):
        raise HarnessError("unknown/duplicate requested module")
    modules = sorted(modules)
    if stage == "core":
        if scope != "change" or level != "auto" or modules:
            raise HarnessError("core stage requires change scope and auto level without --module")
        actual, chosen = ("documentation" if all(documentation_path(path) for path in paths)
                          else "core-limited"), []
        reasons = [*reasons, "ADR0027: bounded fixed-read only; hardening/release remain unverified"]
    elif scope == "bootstrap":
        if level != "auto" or modules:
            raise HarnessError("bootstrap cannot claim a validation level")
        actual, chosen = "bootstrap", []
    elif scope == "release" or level == "release":
        if modules or (scope == "release" and level not in {"auto", "release"}):
            raise HarnessError("release requires its complete profile")
        actual, chosen = "release", []
    elif level == "system":
        if modules:
            raise HarnessError("system uses all owners; --module is invalid")
        actual, chosen = "system", []
    elif level in {"module", "pair"}:
        chosen = modules or affected
        if (minimum not in {"module", "pair"} or not set(affected).issubset(chosen)
                or any(registry["modules"][name]["state"] != "ready" for name in chosen)):
            raise HarnessError("requested level would omit required validation closure")
        if level == "module" and (minimum != "module" or len(chosen) != 1):
            raise HarnessError("module level requires exactly one mapped owner")
        if level == "pair":
            matching = [name for name, item in registry["pairs"].items() if set(item["modules"]) == set(chosen)]
            if len(matching) != 1:
                raise HarnessError("pair level requires one registered real producer/consumer closure")
            pair = matching[0]
        actual = level
    else:
        if modules:
            raise HarnessError("--module requires an explicit module or pair level")
        actual, chosen = minimum, affected if minimum in {"module", "pair"} else []
    if actual == "core-limited":
        suites = core_suites(root, paths, policy)
        components, closure = {}, source_inventory(root, policy, architecture,
                                                   ["alpha"])
    elif actual in {"module", "pair"}:
        suites, components = _scoped_suites(policy, registry, chosen, pair if actual == "pair" else None)
        closure = source_inventory(root, policy, architecture, chosen)
    else:
        components, closure = {}, {}
        names = (policy["release_suites"] if actual == "release" else
                 list(policy["suites"]) if actual == "system" else policy["bootstrap_suites"])
        if actual == "system":
            legacy_required = legacy_plan(root, paths, policy, architecture, invariants)["required_suites"]
            names = [name for name in names if policy["suites"][name]["state"] == "ready" or name in legacy_required]
        suites = {name: policy["suites"][name] for name in names}
        if actual == "documentation":
            # No contracts/native tests for prose. Executable/config changes
            # retain engineering/system classification and cannot enter here.
            suites = {"repository": policy["suites"]["repository"]}
        if actual == "engineering":
            suites["engineering-native"] = {"state": "ready", "timeout_seconds": policy["suites"]["rust"]["timeout_seconds"],
                "commands": [["{python}", "scripts/cargo.py", "test", "--package", "guradb", "--locked"]]}
        if actual in {"system", "release"}:
            closure = source_inventory(root, policy, architecture, sorted(architecture["modules"]))
    profile = {"level": actual, "modules": chosen, "pairs": [pair] if actual == "pair" else [],
               "registry_sha256": digest(registry), "policy_sha256": digest(policy),
               "architecture_sha256": digest(architecture), "source_closure": closure,
               "denominator": {"rule": "complete-owner-production-sources", "threshold_percent": dict(THRESHOLDS),
                               "sources": sorted(closure)} if closure else {"rule": "not-production-coverage"},
               "components": components, "suites": suites, "reuse": "none; every command fresh",
               "required_closure": required}
    if actual == "core-limited":
        profile["denominator"] = {"rule": "source-binding-only; no coverage qualification", "sources": sorted(closure)}
        profile["limitations"] = ["simple local Rust alpha only", "hardening not assessed", "release not assessed"]
    return {"requested_level": level, "requested_modules": modules, "stage": stage, "core_flow": core_flow,
            "minimum_level": minimum,
            "selection_reasons": reasons, "profile": profile, "profile_sha256": digest(profile),
            "legacy_impact": legacy_plan(root, paths, policy, architecture, invariants)}
