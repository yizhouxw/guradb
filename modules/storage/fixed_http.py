"""Finite HTTP/1.1 response metadata. No decompression or transfer decoding."""
import re

from modules.common.cf1a_primitives import ContractFailure, require

HEADER_LIMIT = 32768
LINE_LIMIT = 8192
HEADER_FIELDS = 64


def response_headers(raw):
    require(len(raw) <= HEADER_LIMIT and raw.endswith(b'\r\n\r\n'),
            'invalid bounded HTTP headers', 'corrupt_object')
    try:
        lines = raw[:-4].decode('ascii').split('\r\n')
    except UnicodeError:
        raise ContractFailure('corrupt_object', 'non-ASCII response headers') from None
    require(all(len(line) <= LINE_LIMIT for line in lines) and
            re.fullmatch(r'HTTP/1\.1 [0-9]{3} [ -~]{0,128}', lines[0]) is not None,
            'unsupported HTTP status line', 'corrupt_object')
    require(len(lines) - 1 <= HEADER_FIELDS, 'too many HTTP header fields', 'corrupt_object')
    headers = {}
    for line in lines[1:]:
        name, colon, value = line.partition(':')
        require(colon and re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) is not None and
                all(32 <= ord(char) <= 126 for char in value),
                'invalid HTTP header field', 'corrupt_object')
        name = name.lower()
        require(name not in headers, 'duplicate HTTP header field', 'corrupt_object')
        headers[name] = value.strip(' ')
    return int(lines[0][9:12]), headers


def validate_response(status, headers, ref, offset, length):
    if status in (401, 403):
        raise ContractFailure('unauthorized', 'backend authentication failed')
    if status == 404:
        raise ContractFailure('missing_object', 'fixed backend version is unavailable')
    if status in (429, 503):
        raise ContractFailure('backend_unavailable', 'backend temporarily unavailable')
    require(status in (200, 206), 'HTTP status is not certified', 'unsupported_capability')
    require('transfer-encoding' not in headers and
            headers.get('content-encoding', 'identity').lower() == 'identity',
            'response transfer or content encoding is not certified', 'unsupported_capability')
    declared = headers.get('content-length', '')
    require(re.fullmatch(r'0|[1-9][0-9]{0,15}', declared) is not None and int(declared) == length,
            'fixed response length mismatch', 'corrupt_object')
    require(headers.get('x-amz-version-id') == ref['version'] and ref['version'] != 'null',
            'fixed response version mismatch', 'corrupt_object')
    require(headers.get('x-amz-delete-marker', 'false').lower() == 'false',
            'fixed version is a delete marker', 'missing_object')
    partial = offset != 0 or length != ref['size_bytes']
    if partial:
        expected = f"bytes {offset}-{offset + length - 1}/{ref['size_bytes']}"
        require(status == 206 and headers.get('content-range') == expected,
                'fixed response range mismatch', 'corrupt_object')
    else:
        require(status == 200 and 'content-range' not in headers,
                'whole response cannot claim a range', 'corrupt_object')
