"""Stable media identity; credentials and expiring signatures are never identity."""
import hashlib
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRANSIENT = {'token', 'expires', 'expire', 'sign', 'signature', 'auth_key', 'wssecret',
             'wstime', 'deadline', 'upsig', 'uipk', 'trid', 'mid', 'os', 'oi', 'platform',
             'policy', 'key-pair-id', 'auth', 'authorization', 'timestamp', 'ts'}


def canonical_url(url):
    parts = urlsplit(url)
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                   if k.lower() not in TRANSIENT and not k.lower().startswith('x-amz-'))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), ''))


def resource_identity(resource):
    # A platform key is only logical identity; quality and stream selection still matter.
    location = resource.get('key') or canonical_url(resource.get('url', ''))
    if not location:
        location = [canonical_url(s.get('url', '')) for s in resource.get('streams', resource.get('segments', []))]
    value = [resource.get('parent_id') or '', location, resource.get('quality') or '',
             resource.get('width') or 0, resource.get('height') or 0,
             [(s.get('kind'), s.get('quality')) for s in resource.get('streams', [])]]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
