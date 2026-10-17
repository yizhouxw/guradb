"""Versioned ASCII BM25 postings with immutable global corpus statistics."""
from collections import Counter
import json
import math
from pathlib import Path
import re

from modules.common.contracts import MAX_BYTES, encoded, require
from modules.storage.objects import get, put

FORMAT = 'bm25-global-v2'
K1 = 1.2
B = .75


def build(directory, rows, text_field, budget):
    """Persist three disjoint posting shards; all use the same global statistics."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    document_frequency, total_tokens = Counter(), 0
    partitions = [[], [], []]
    for ordinal, row in enumerate(sorted(rows, key=lambda row:row['logical_key'])):
        budget.check()
        text = row['values'][text_field] or ''
        counts = Counter(re.findall(r'[A-Za-z0-9]+', text.lower()))
        length = sum(counts.values())
        total_tokens += length
        document_frequency.update(counts.keys())
        partitions[ordinal % 3].append({'key':row['logical_key'], 'length':length, 'terms':dict(counts)})
    stats = {'format':FORMAT, 'documents':len(rows), 'total_tokens':total_tokens,
             'document_frequency':dict(document_frequency), 'k1':K1, 'b':B}
    files, total_bytes = [], 0
    for n, part in enumerate(partitions):
        raw = encoded(part)
        total_bytes += len(raw)
        require(total_bytes <= MAX_BYTES, 'resource_limit', 'BM25 postings exceed byte budget')
        files.append(put(directory/(str(n)+'.json'), raw))
    raw = encoded(stats)
    require(len(raw)+total_bytes <= MAX_BYTES, 'resource_limit', 'BM25 index exceeds byte budget')
    return {'format':FORMAT, 'stats':put(directory/'statistics.json', raw), 'files':files,
            'bytes':total_bytes+len(raw)}


def ranked(bundle, text, allowed, budget):
    """Return exact BM25 scores using corpus-wide statistics before filtering."""
    index = bundle['bm25']
    require(index.get('format') == FORMAT, 'source_invalid')
    require(isinstance(text, str) and len(text) <= 512 and
            re.fullmatch(r'[A-Za-z0-9 ]+', text) is not None, 'invalid_request')
    tokens = text.lower().split()
    require(0 < len(tokens) <= 16 and all(len(t) <= 40 for t in tokens), 'invalid_request')

    def read(reference):
        raw = get(reference)
        budget.artifact(len(raw))
        return json.loads(raw)

    stats = read(index['stats'])
    require(stats['format'] == FORMAT and stats['k1'] == K1 and stats['b'] == B and
            type(stats['documents']) is int and stats['documents'] > 0, 'source_invalid')
    average = stats['total_tokens']/stats['documents']
    scores, seen = [], set()
    for reference in index['files']:
        for posting in read(reference):
            budget.check()
            logical = posting['key']
            require(logical not in seen, 'source_invalid')
            seen.add(logical)
            if logical not in allowed:
                continue
            contributions = []
            for token in tokens:
                frequency = posting['terms'].get(token, 0)
                if not frequency:
                    continue
                df = stats['document_frequency'][token]
                require(1 <= df <= stats['documents'] and average > 0, 'source_invalid')
                idf = math.log1p((stats['documents']-df+.5)/(df+.5))
                denominator = frequency + K1*(1-B+B*posting['length']/average)
                contributions.append(idf*frequency*(K1+1)/denominator)
            if contributions:
                scores.append((logical, math.fsum(contributions)))
    require(allowed <= seen, 'source_invalid', 'BM25 shard does not cover assigned identities')
    return sorted(scores, key=lambda hit:(-hit[1],hit[0]))
