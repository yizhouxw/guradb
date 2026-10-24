"""Actual Python import graph for production modules, including ownership edges."""
import ast
from pathlib import Path
import sys

from .policy import HarnessError, owner, production_source


def check(root, paths, policy, architecture, cycle_check):
    sources = {p.relative_to(root).with_suffix('').as_posix().replace('/','.'): p for p in paths
               if p.suffix=='.py' and production_source(p.relative_to(root).as_posix(),policy)}
    graph = {name:set() for name in sources}
    external = set(architecture.get('python',{}).get('external',[]))
    for name,path in sources.items():
        module = owner(path.relative_to(root).as_posix(),architecture)
        try:
            tree = ast.parse(path.read_text(),filename=str(path))
        except SyntaxError as error:
            raise HarnessError(f'{path}: invalid Python syntax') from error
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == 'importlib':
                metadata = parents.get(node)
                version = parents.get(metadata)
                call = parents.get(version)
                if not (isinstance(node.ctx, ast.Load)
                        and isinstance(metadata, ast.Attribute) and metadata.attr == 'metadata'
                        and isinstance(version, ast.Attribute) and version.attr == 'version'
                        and isinstance(version.ctx, ast.Load)
                        and isinstance(call, ast.Call) and call.func is version):
                    raise HarnessError(f'{path}: importlib bypasses checked production graph')
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in ('__import__','eval','exec'):
                raise HarnessError(f'{path}: dynamic code/import bypasses checked Python graph')
            imports = []
            if isinstance(node,ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node,ast.ImportFrom):
                if node.level:
                    raise HarnessError(f'{path}: use explicit absolute production imports')
                base = node.module or ''
                if base.split('.')[0] in ('modules','clients') and base not in sources and not any(source.startswith(base+'.') for source in sources):
                    raise HarnessError(f'{path}: unresolved local Python import {base}')
                imports = [base]
                imports += [(base+'.'+alias.name) for alias in node.names if base and base+'.'+alias.name in sources]
            for target in imports:
                top = target.split('.')[0]
                if top in ('modules','clients'):
                    if target in sources:
                        dependency = owner(sources[target].relative_to(root).as_posix(),architecture)
                        if dependency != module and dependency not in architecture['modules'][module]['allowed']:
                            raise HarnessError(f'forbidden Python module dependency: {module} -> {dependency}')
                        graph[name].add(target)
                    elif not any(source.startswith(target+'.') for source in sources) and isinstance(node,ast.Import):
                        raise HarnessError(f'{path}: unresolved local Python import {target}')
                elif top not in sys.stdlib_module_names and top not in external:
                    raise HarnessError(f'{path}: undeclared external Python import {top}')
                if top=='importlib' and not (target == 'importlib.metadata'
                        and isinstance(node, ast.Import)
                        and all(alias.name != target or alias.asname is None for alias in node.names)):
                    raise HarnessError(f'{path}: importlib bypasses checked production graph')
    cycle_check(graph)
    return f'Python AST import DAG checked for {len(sources)} production modules'
