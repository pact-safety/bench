"""Authenticate pilot evidence kept in otherwise owner-editable settings."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import json
import os


_DOMAIN = b'bench-track-assessment-v1\x00'


def _signature(record: dict) -> str:
    key = os.environ.get('TRACK_ASSESSMENT_SIGNING_KEY', '')
    if len(key) < 32 or not key.strip():
        raise RuntimeError('Set TRACK_ASSESSMENT_SIGNING_KEY to a stable secret of at least 32 characters before accepting or reviewing track assessments.')
    if not isinstance(record.get('user_id'), str) or not record['user_id']:
        raise ValueError('Assessment evidence must identify its owner.')
    payload = {k: v for k, v in record.items() if k != 'integrity_signature'}
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hmac.new(key.encode('utf-8'), _DOMAIN + canonical, hashlib.sha256).hexdigest()


def sign_record(record: dict) -> dict:
    """Return a deep-copied record signed with the dedicated server secret."""
    signed = deepcopy(record)
    signed['integrity_signature'] = _signature(signed)
    return signed


def verify_record(record: object, user_id: str | None = None) -> bool:
    """Fail closed for altered, unsigned, misowned, or unverifiable evidence."""
    if not isinstance(record, dict) or (user_id is not None and record.get('user_id') != user_id):
        return False
    signature = record.get('integrity_signature')
    if not isinstance(signature, str) or len(signature) != 64:
        return False
    try:
        return hmac.compare_digest(signature, _signature(record))
    except (RuntimeError, ValueError, TypeError, UnicodeError):
        return False
