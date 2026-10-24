"""Private CF1-A reader for one protected revision with one or two fixed sources.

The first page validates the entire bounded input. This is not a production
streaming provider, an ingest reader, or a public locator/projection API.
"""
import threading

from modules.common.cf1a_ports import SourceReadPort
from modules.common.cf1a_primitives import ContractFailure, canonical, digest, require, validate_shape
from modules.common.cf1a_read import validate_access, validate_batch_for, without
from modules.common.cf1a_schema import I53, VERSION
from modules.common.cf1a_wire import Contract
from modules.common.contracts import key
from modules.connectors.fixed_parquet_pages import decode_group
from modules.connectors.fixed_parquet_plan import footer
from modules.connectors.fixed_source_inputs import fixed_inputs
from modules.connectors.fixed_source_located import encode_located, joint_bound
from modules.connectors.fixed_source_scope import SourceScope
from modules.storage.fixed_objects import FixedObjects

MAX_ENVELOPE = 768 << 10


def envelope(value):
    return {'contract_version': VERSION,
            'required_capabilities': ['fixed_read', 'typed_json_v1', 'strong_integrity'],
            'payload': {'read_batch': value}}


def record(values, source, fields, revision):
    mappings = {entry['resource_field_id']: entry for entry in source['field_mapping']}
    cells, roles = [], {}
    for field in fields:
        mapping = mappings[field['field_id']]
        value = revision if mapping['transform'] == 'revision_version' else values[mapping['source_field_id']]
        if mapping['transform'] == 'key_v1':
            require(value is not None, 'NULL logical source key', 'corrupt_object')
            if mapping['source_type'] == 'text':
                require(len(value.encode('utf-8')) <= 54, 'encoded logical key exceeds A ID bound',
                        'resource_limit')
            value = key(value, 'string' if mapping['source_type'] == 'text' else 'long')
        if value is None:
            require(field['nullable'], 'NULL in nonnullable mapped field', 'corrupt_object')
            cell = {'type': 'null', 'value': None}
        else:
            cell = {'type': field['type'], 'value': str(value) if field['type'] == 'int8' else value}
            validate_shape(cell, 'cell')
        if field['role'] != 'value':
            validate_shape(value, 'id')
            roles[field['role']] = value
        cells.append(cell)
    return {'record_id': roles['logical_id'], 'record_version': roles['record_version'], 'cells': cells}


def row_wire_bound(values, source, fields):
    """A conservative bound before creating typed dicts or canonical JSON.

    Escaping a UTF8 byte costs at most six JSON bytes; int8 is at most 20 digits,
    a derived ID at most128 characters. Fixed keys/structure have ample room.
    """
    bound = 1024
    by_id = {item['resource_field_id']: item for item in source['field_mapping']}
    for field in fields:
        mapping = by_id[field['field_id']]
        value = values.get(mapping['source_field_id'])
        width = len(value.encode('utf-8')) if type(value) is str else 128
        if mapping['transform'] == 'key_v1':
            width = 128
        bound += 128 + 6 * width
    return bound


class FixedSourceReader:
    def __init__(self, objects):
        require(type(objects) is FixedObjects and type(objects.scope) is SourceScope
                and getattr(objects.port.read, '__self__', None) is objects,
                'source requires the same trusted fixed object scope', 'unsupported_capability')
        self.objects, self.scope = objects, objects.scope
        self._binding = self.scope.binding
        self._state = None
        self._failed = False
        self._reader_lock = threading.Lock()
        self.last_observation = None
        self.port = SourceReadPort(self.read_batch)

    def _authorize(self, binding):
        require(binding == self._binding.value, 'source binding differs from issued binding')
        self.objects.authorize()

    def _load(self):
        scope = self.scope
        # Covers descriptor JSON copies/strings, lookup dictionaries and state.
        with scope.reserve(len(self._binding.encoded) * 32 + 16384) as descriptors:
            binding = self._binding.value
            self._authorize(binding)
            fields = binding['resource']['fields']
            with fixed_inputs(self.objects, self._binding, binding, scope) as (inputs, rows, working):
                with scope.reserve(working) as retained:
                    records, costs, locations, seen = [], [], {}, set()
                    for source, metadata in inputs:
                        for entry in metadata['files']:
                            ref = entry['object']
                            data = self.objects.port.read(self._binding, ref, 0, ref['size_bytes'])
                            plans = footer(data, metadata['source_schema'], entry['row_group_rows'], scope)
                            for group, (plan, count) in enumerate(zip(plans, entry['row_group_rows'])):
                                decoded = decode_group(data, plan, count, scope)
                                for offset, values in enumerate(decoded):
                                    scope.check()
                                    bound = row_wire_bound(values, source, fields)
                                    require(bound < MAX_ENVELOPE, 'one fixed source row cannot fit', 'resource_limit')
                                    with scope.reserve(bound * 32):
                                        result = record(values, source, fields, binding['revision']['data_revision_id'])
                                        encoded_size = len(canonical(result))
                                    require(encoded_size <= bound, 'fixed row encoding exceeded reservation', 'resource_limit')
                                    identifier = result['record_id']
                                    require(identifier not in seen, 'duplicate logical source identity', 'corrupt_object')
                                    seen.add(identifier)
                                    records.append(result)
                                    costs.append((identifier, encoded_size))
                                    locations[identifier] = {'source_version_id': source['source_version_id'],
                                        'object': ref, 'row_group': group, 'row_offset': offset}
                    require(len(records) == rows, 'incomplete fixed source enumeration', 'corrupt_object')
                    scope.check()
                    records.sort(key=lambda row: row['record_id'])
                    state = {'binding': binding, 'records': records, 'locations': locations,
                             'costs': dict(costs)}
                    state['locator_bounds'] = {(source['source_version_id'], canonical(entry['object'])):
                        tuple(entry['row_group_rows']) for source, metadata in inputs for entry in metadata['files']}
                    state['pages'] = self._pages(state, dict(costs))
                    self._authorize(binding)
                    self._state = state
                    retained.keep(working)
            descriptors.keep(descriptors.size)

    def _value(self, state, ordinal, rows, usage, last):
        resource = state['binding']['resource']
        return {'context_sha256': self._binding.sha256, 'schema_id': resource['schema_id'],
                'schema_version': resource['schema_version'], 'fields': resource['fields'],
                'batch_ordinal': ordinal, 'last': last, 'truncated': False,
                'ordering': 'logical_id_asc', 'rows': rows, 'usage': usage,
                'content_sha256': '0' * 64}

    def _pages(self, state, costs):
        # Max safe integer widths and last=false make this independent of actual
        # Usage/ordinal values. The boundary caps the complete envelope, not rows.
        usage = {name: I53 for name in ('object_requests', 'object_bytes', 'memory_bytes',
                                        'output_bytes', 'elapsed_ms')}
        overhead = len(canonical(envelope(self._value(state, I53, [], usage, False))))
        state['overhead'] = overhead
        pages, start, size = [], 0, overhead
        for index, row in enumerate(state['records']):
            self.scope.check()
            cost = costs[row['record_id']] + (index > start)
            require(overhead + costs[row['record_id']] <= MAX_ENVELOPE,
                    'one fixed source row cannot fit', 'resource_limit')
            if index - start == 64 or size + cost > MAX_ENVELOPE:
                pages.append((start, index))
                start, size, cost = index, overhead, costs[row['record_id']]
            size += cost
        pages.append((start, len(state['records'])))
        return pages

    def _batch(self, ordinal, before):
        state, scope = self._state, self.scope
        require(ordinal < len(state['pages']), 'source ordinal is beyond terminal page')
        start, end = state['pages'][ordinal]
        rows = state['records'][start:end]
        # Bound complete wire from actual fixed row bytes before Contract's JSON
        # copies/validation.32x covers decoded dicts, strings and encode copies.
        bound = state['overhead'] + sum(state['costs'][row['record_id']] + 1 for row in rows)
        with scope.reserve(bound * 32) as output_memory:
            self._authorize(state['binding'])
            first = self._encode(ordinal, rows, scope.batch_usage(before), bound)
            del first
            self._authorize(state['binding'])
            # Observe after the complete first construction and validation.
            # An immutable envelope necessarily precedes its final serialization
            # tail; real acceptance times the whole call and records that tail.
            usage = scope.batch_usage(before)
            observed = scope.monotonic()
            result = self._encode(ordinal, rows, usage, bound)
            self._authorize(state['binding'])
            # Returned wire is retained until the query scope is discarded.
            output_memory.keep(len(result.encoded) + 64)
            precommit = scope.monotonic()
            self.last_observation = {'observed_monotonic_s': observed,
                'precommit_monotonic_s': precommit, 'usage_elapsed_ms': usage['elapsed_ms'],
                'observed_finalization_ms': (precommit - observed) * 1000,
                'observed_page_elapsed_ms': (precommit - scope.batch_started) * 1000}
            # Final policy check and ledger commit. Nothing after this point
            # performs an application-level reject of this returned envelope.
            scope.delivered(len(result.encoded))
            return result

    def _encode(self, ordinal, rows, usage, bound):
        value = self._value(self._state, ordinal, rows, usage,
                            ordinal + 1 == len(self._state['pages']))
        original_output = usage['output_bytes']
        for _ in range(4):
            value['content_sha256'] = digest(without(value, 'content_sha256'))
            raw = canonical(envelope(value))
            expected = original_output + len(raw)
            if usage['output_bytes'] == expected:
                break
            usage['output_bytes'] = expected
        else:
            require(False, 'batch output accounting did not converge', 'resource_limit')
        require(len(raw) <= MAX_ENVELOPE and len(raw) <= bound,
                'fixed batch envelope exceeds bound', 'resource_limit')
        self.scope.output(len(raw))
        result = Contract(raw)
        require(result.encoded == raw, 'batch canonical bytes changed', 'corrupt_object')
        validate_batch_for(self._binding, result)
        return result

    def _located_batch(self, ordinal, before):
        state, scope = self._state, self.scope
        require(ordinal < len(state['pages']), 'source ordinal is beyond terminal page')
        start, end = state['pages'][ordinal]
        rows = state['records'][start:end]
        ordinary = state['overhead'] + sum(state['costs'][row['record_id']] + 1 for row in rows)
        bound = joint_bound(rows, state['locations'], ordinary, scope.check)
        with scope.reserve(bound * 32) as output_memory:
            self._authorize(state['binding'])
            first = encode_located(self._binding,
                self._value(state, ordinal, rows, scope.batch_usage(before), ordinal + 1 == len(state['pages'])),
                state['locations'], state['locator_bounds'], scope, bound)
            del first
            self._authorize(state['binding'])
            usage = scope.batch_usage(before)
            observed = scope.monotonic()
            result = encode_located(self._binding,
                self._value(state, ordinal, rows, usage, ordinal + 1 == len(state['pages'])),
                state['locations'], state['locator_bounds'], scope, bound)
            self._authorize(state['binding'])
            output_memory.keep(result.wire_bytes + 128)
            precommit = scope.monotonic()
            self.last_observation = {'observed_monotonic_s': observed,
                'precommit_monotonic_s': precommit, 'usage_elapsed_ms': usage['elapsed_ms'],
                'observed_finalization_ms': (precommit - observed) * 1000,
                'observed_page_elapsed_ms': (precommit - scope.batch_started) * 1000}
            scope.delivered(result.wire_bytes)
            return result

    def read_batch(self, binding, ordinal):
        return self._read(binding, ordinal, located=False)

    def read_located_batch(self, binding, ordinal):
        return self._read(binding, ordinal, located=True)

    def _read(self, binding, ordinal, *, located):
        # A non-owner cannot clear or poison another call's shared state.
        require(self._reader_lock.acquire(blocking=False),
                'concurrent fixed source reads rejected', 'resource_limit')
        try:
            require(type(ordinal) is int and ordinal >= 0 and binding.encoded == self._binding.encoded,
                    'fixed source binding or ordinal mismatch')
            require(not self._failed, 'fixed source failed; a fresh scope is required', 'expired_context')
            with self.scope.batch():
                before = self.scope.usage()
                if self._state is None:
                    self._load()
                return self._located_batch(ordinal, before) if located else self._batch(ordinal, before)
        except BaseException:
            self._state = None
            self._failed = True
            raise
        finally:
            self._reader_lock.release()
