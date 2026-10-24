"""Reopen physical P06 artifacts through ObjectReadPort and emit CF1-A candidates."""
import heapq
from modules.common.cf1a_primitives import ContractFailure, canonical, require
from modules.common.cf1a_ports import ArtifactReadPort
from modules.common.cf1a_read import validate_candidates_for
from modules.index.fixed_artifacts import ALGORITHMS, FORMATS, MODEL_FIELDS, read_manifest, validate_body
from modules.index.fixed_layout import MAX_FILE_BYTES, envelope, f64_hex, strict_json, verified_bytes
from modules.index.fixed_scope import delta_usage


class FixedArtifactReader:
    """No source reads or candidate cache; one injected parent scope accumulates IO."""
    def __init__(self, objects, scope):
        self.objects = objects
        self.scope = scope

    def _artifact(self, binding, artifact_id):
        self.scope.matches(binding)
        artifact = next((item for item in binding.value['indexes'] if item['artifact_id'] == artifact_id), None)
        require(artifact is not None, 'artifact is not in fixed view')
        require(artifact['kind'] in ALGORITHMS and artifact['shard_count'] == 1 and len(artifact['shards']) == 1,
                'unsupported physical artifact', 'unsupported_version')
        require(artifact['format_id'] == FORMATS[artifact['kind']] and artifact['format_version'] == 1,
                'unsupported private format', 'unsupported_version')
        return artifact

    def _read(self, ref):
        require(ref['size_bytes'] <= MAX_FILE_BYTES, 'private object exceeds reader bound', 'resource_limit')
        raw = self.scope.read(self.objects, ref)
        verified_bytes(raw, ref)
        self.scope.metrics['checksum_bytes'] += len(raw)
        return raw

    def _load(self, binding, artifact):
        raw = self._read(artifact['shards'][0])
        try:
            body = strict_json(raw)
            require(type(body) is dict and type(body.get('header')) is dict and
                    'processing_manifest' in body['header'], 'missing processing input')
            ref = body['header']['processing_manifest']
            # The dependency must be fixed/protected before any second object request.
            require(ref in binding.value['revision']['objects'], 'unprotected processing input')
            self.scope.charge('memory_bytes', (len(raw) + ref['size_bytes']) * 64)
            manifest_raw = self._read(ref)
            manifest = read_manifest(manifest_raw, ref, binding)
            validate_body(body, artifact, manifest, ref)
            self.scope.metrics['decoded_bytes'] += len(raw) + len(manifest_raw)
            self.scope.checkpoint()
            return raw, body
        except ContractFailure as error:
            if error.code in ('invalid_contract', 'unsupported_version'):
                raise ContractFailure('corrupt_object', 'invalid sealed artifact/processing layout') from error
            raise

    def read_artifact(self, binding, artifact_id):
        artifact = self._artifact(binding, artifact_id)
        raw, _ = self._load(binding, artifact)
        self.scope.charge('output_bytes', len(raw))
        self.scope.checkpoint()
        return raw

    def candidates(self, binding, query):
        require(query.kind == 'index_query', 'expected index query')
        request = query.value
        artifact = self._artifact(binding, request['artifact_id'])
        require(request['context_sha256'] == binding.sha256 and
                all(request[name] == artifact[name] for name in ('kind', *MODEL_FIELDS)) and
                request['configuration_sha256'] == artifact['configuration_sha256'], 'query artifact/context mismatch')
        require(request['top_k'] <= binding.value['context']['budget']['top_k'] and
                request['candidate_limit'] <= binding.value['context']['budget']['candidates'],
                'query exceeds parent candidate budget', 'resource_limit')
        before = self.scope.snapshot()
        _, body = self._load(binding, artifact)
        algorithm = ALGORITHMS[artifact['kind']]
        argument = request['query_text'] if artifact['kind'] == 'bm25' else request['query_vector_f64_hex']
        if artifact['kind'] == 'bm25':
            scores = algorithm.score(body['rows'], body['statistics'], argument, self.scope.scan)
        else:
            scores = algorithm.score(body['rows'], argument, self.scope.scan)
        allowed = set(request['allowed_record_ids']) if request['filter_mode'] == 'ids' else None
        descending = artifact['kind'] == 'bm25'
        filtered = ((identity, score) for identity, score in scores if allowed is None or identity in allowed)
        # Bounded retained candidates, while the iterator still scans every eligible source row.
        scores = heapq.nsmallest(request['candidate_limit'], filtered,
                                key=lambda item: (-item[1] if descending else item[1], item[0]))
        by_id = {row['record_id']: row for row in body['ledger']}
        rows = [{'record_id': identity, 'record_version': by_id[identity]['record_version'],
                 'score_f64_hex': f64_hex(score), 'locator': by_id[identity]['locator']}
                for identity, score in scores[:request['top_k']]]
        usage = delta_usage(before, self.scope.snapshot())
        value = {'context_sha256': binding.sha256, 'index_query_sha256': query.sha256,
                 'artifact_id': artifact['artifact_id'], 'metric': artifact['metric'],
                 'score_order': 'descending' if descending else 'ascending', 'complete': True,
                 'rows': rows, 'usage': usage}
        # Output byte accounting includes its own counter, with a bounded fixed point.
        for _ in range(8):
            result = envelope('candidate_batch', value)
            size = len(result.encoded)
            if value['usage']['output_bytes'] == size:
                break
            value['usage']['output_bytes'] = size
        require(value['usage']['output_bytes'] == len(result.encoded), 'unstable output accounting')
        self.scope.charge('output_bytes', len(result.encoded))
        validate_candidates_for(binding, query, result)
        self.scope.checkpoint()
        return result

    def port(self):
        return ArtifactReadPort(candidates=self.candidates, read_artifact=self.read_artifact)
