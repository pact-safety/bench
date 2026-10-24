from copy import deepcopy

import pytest

from app.services.track_assessment_integrity import sign_record, verify_record


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setenv('TRACK_ASSESSMENT_SIGNING_KEY', 'unit-test-only-track-assessment-key-0001')


def record():
    return {'id': 'submission', 'user_id': 'owner', 'state': 'pending',
            'responses': {'answers': 'My reasoning', 'transcript_confirmed': True},
            'modality': 'oral', 'assistance': 'none', 'spec_version': 'v1'}


def test_signing_returns_copy_and_checks_owner():
    original = record()
    before = deepcopy(original)
    signed = sign_record(original)
    assert original == before and 'integrity_signature' not in original
    assert verify_record(signed, 'owner') is True
    assert verify_record(signed, 'other-owner') is False
    signed['responses']['answers'] = 'Changed'
    assert original == before
    assert verify_record(signed, 'owner') is False


@pytest.mark.parametrize('field,value', [
    ('user_id', 'other'), ('state', 'reviewed'), ('spec_version', 'v2'),
    ('assistance', 'help'), ('modality', 'written'),
    ('review', {'verdict': 'approved'}), ('practical_passed', {'verified_slugs': ['forged']}),
])
def test_any_record_field_tampering_invalidates_signature(field, value):
    signed = sign_record(record())
    signed[field] = value
    assert verify_record(signed, signed['user_id']) is False


def test_json_key_order_does_not_change_signature():
    original = record()
    signed = sign_record(original)
    reordered = dict(reversed(list(signed.items())))
    reordered['responses'] = dict(reversed(list(reordered['responses'].items())))
    assert verify_record(reordered, 'owner')
    assert sign_record(reordered)['integrity_signature'] == signed['integrity_signature']


@pytest.mark.parametrize('key', ['', 'short', ' ' * 40])
def test_unconfigured_key_fails_closed_with_actionable_sign_error(monkeypatch, key):
    signed = sign_record(record())
    monkeypatch.setenv('TRACK_ASSESSMENT_SIGNING_KEY', key)
    with pytest.raises(RuntimeError, match='TRACK_ASSESSMENT_SIGNING_KEY'):
        sign_record(record())
    assert verify_record(signed, 'owner') is False


def test_key_rotation_invalidates_previous_signatures(monkeypatch):
    signed = sign_record(record())
    monkeypatch.setenv('TRACK_ASSESSMENT_SIGNING_KEY', 'unit-test-only-other-assessment-key-0002')
    assert verify_record(signed, 'owner') is False


@pytest.mark.parametrize('value', [None, [], {}, {'user_id': 'owner'}, {'user_id': 'owner', 'integrity_signature': 42}])
def test_missing_or_malformed_signature_is_not_verified(value):
    assert verify_record(value, 'owner') is False
