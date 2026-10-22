"""One fixed revision's metadata closure and aggregate preflight, never a reader.

Every source uses the caller's existing object port, binding, scope and ledger.
All metadata is validated before any data object is requested.
"""
from contextlib import contextmanager, ExitStack

from modules.common.cf1a_primitives import require
from modules.connectors.fixed_source_manifest import MAX_METADATA, manifest, object_reference


@contextmanager
def fixed_inputs(objects, contract, binding, scope):
    sources, fields = binding['revision']['sources'], binding['resource']['fields']
    require(1 <= len(sources) <= 2 and all(source['format'] == 'manifest'
            and source['format_version'] == '1' for source in sources),
            'only one or two fixed manifest/1 sources are certified', 'unsupported_capability')
    require(len(fields) <= 32, 'fixed resource field count exceeds bound', 'resource_limit')
    references = [source['metadata'] for source in sources]
    metadata_ids = [object_reference(ref) for ref in references]
    require(len(metadata_ids) == len(set(metadata_ids)), 'shared fixed metadata object')
    require(sum(ref['size_bytes'] for ref in references) <= MAX_METADATA,
            'combined fixed metadata exceeds bound', 'resource_limit')
    with ExitStack() as stack:
        parsed, holds = [], []
        for source in sources:
            scope.check()
            ref = source['metadata']
            raw = objects.port.read(contract, ref, 0, ref['size_bytes'])
            hold = stack.enter_context(scope.reserve(len(raw) * 32 + 65536))
            holds.append(hold)
            parsed.append((source, manifest(raw, source, scope)))
        members = set(metadata_ids)
        rows = groups = size = count = working = width_total = 0
        for source, metadata in parsed:
            scope.check()
            files = metadata['files']
            count += len(files)
            source_rows = sum(sum(entry['row_group_rows']) for entry in files)
            source_groups = sum(len(entry['row_group_rows']) for entry in files)
            source_size = sum(entry['object']['size_bytes'] for entry in files)
            rows += source_rows
            groups += source_groups
            size += source_size
            width = len(metadata['source_schema'])
            width_total += width
            working += (4 * source_size + source_rows * (160 * width + 320 * len(fields) + 1024)
                        + source_groups * width * 1024)
            for entry in files:
                identity = object_reference(entry['object'])
                require(identity not in members, 'shared fixed data or metadata used as data')
                members.add(identity)
        require(count <= 4 and groups <= 16 and rows <= 1000 and size <= 4 << 20
                and width_total <= 32,
                'combined fixed source bounds exceeded', 'resource_limit')
        revision_objects = {object_reference(ref) for ref in binding['revision']['objects']}
        require(members == revision_objects,
                'fixed revision objects do not exactly match all metadata and data',
                'unsupported_capability')
        scope.check()
        yield parsed, rows, working + 16384
        # Preserve the original conservative retained metadata ownership on success.
        # On a failure ExitStack releases only these reservations, never I/O fees.
        for hold in holds:
            hold.keep(hold.size)
