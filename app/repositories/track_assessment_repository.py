"""Owner-scoped pilot assessments, stored without a schema migration."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from urllib.parse import urlsplit
from uuid import UUID

from .. import cache
from ..services.track_assessment_integrity import sign_record, verify_record


MAX_SUBMISSIONS = 30
MAX_ANSWERS = 12000


class AssessmentConflictError(ValueError):
    pass


class AssessmentHistoryFullError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _request_id(value):
    if not isinstance(value, str) or len(value) > 36:
        raise ValueError("A valid submission token is required.")
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError("A valid submission token is required.") from exc


def _records(row):
    settings = row.get('settings_json') or {}
    if not isinstance(settings, dict):
        raise ValueError("Saved settings are unavailable; no assessment was changed.")
    records = settings.get('track_assessments', [])
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ValueError("Saved assessment history is invalid; no assessment was changed.")
    return deepcopy(records)


def _identity(spec):
    return {'track_slug': spec['track_slug'], 'section_idx': spec['section_idx'],
            'spec_id': spec['id'], 'spec_version': spec['version']}


def _responses(value, modality):
    if not isinstance(value, dict) or set(value) != {'answers', 'artifact_url', 'transcript_confirmed'}:
        raise ValueError("Supply confirmed text, a work link, and transcript confirmation only.")
    answers, url = value['answers'], value['artifact_url']
    if not isinstance(answers, str) or not answers.strip() or len(answers) > MAX_ANSWERS:
        raise ValueError(f"Answers must contain 1–{MAX_ANSWERS} characters.")
    if type(value['transcript_confirmed']) is not bool or (modality == 'oral' and not value['transcript_confirmed']):
        raise ValueError("Confirm the oral transcript before submitting.")
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("The supporting work link is too long.")
    if url:
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme in {'http', 'https'} and parsed.hostname
                     and not parsed.username and not parsed.password
                     and not any(c.isspace() or ord(c) < 32 for c in url))
            parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("The supporting work link must be an HTTP(S) URL.")
    return deepcopy(value)


def _practical(value):
    if value == {}:
        return {}
    if not isinstance(value, dict) or set(value) != {'verified_slugs', 'checked_at'}:
        raise ValueError("Practical evidence must be checked on the server.")
    slugs = value['verified_slugs']
    if (not isinstance(slugs, list) or len(slugs) > 20
            or any(not isinstance(s, str) or not s or len(s) > 200 for s in slugs)):
        raise ValueError("Invalid practical evidence.")
    try:
        checked = datetime.fromisoformat(value['checked_at'])
        if checked.tzinfo is None:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("Practical evidence needs a timestamp.") from None
    return {'verified_slugs': sorted(set(slugs)), 'checked_at': value['checked_at']}


class TrackAssessmentRepository:
    def __init__(self, conn):
        self.conn = conn

    def list_for_user(self, user_id):
        with self.conn.cursor() as cur:
            cur.execute("SELECT settings_json FROM public.users WHERE id = %s", (user_id,))
            row = cur.fetchone()
        return _records(row) if row else []

    def get(self, user_id, assessment_id):
        try:
            assessment_id = _request_id(assessment_id)
        except ValueError:
            return None
        return next((r for r in self.list_for_user(user_id) if r.get('id') == assessment_id), None)

    def pending_reviews(self, limit=100):
        """Cross-owner review queue; callers must enforce the administrator gate."""
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Review queue limit must be between 1 and 200.")
        with self.conn.cursor() as cur:
            cur.execute("""SELECT u.id AS user_id, a.record FROM public.users u
                CROSS JOIN LATERAL jsonb_array_elements(CASE
                    WHEN jsonb_typeof(u.settings_json->'track_assessments') = 'array'
                    THEN u.settings_json->'track_assessments' ELSE '[]'::jsonb END) AS a(record)
                WHERE a.record->>'state' = 'pending'
                ORDER BY a.record->>'submitted_at', u.id LIMIT %s""", (limit,))
            return [{**r['record'], 'user_id': str(r['user_id'])} for r in cur.fetchall()]

    def _locked(self, cur, user_id):
        cur.execute("SELECT settings_json FROM public.users WHERE id = %s FOR UPDATE", (user_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Assessment user does not exist.")
        return _records(row)

    def _write(self, cur, user_id, records):
        # Update only our key: never replay a cached copy of unrelated settings.
        cur.execute("""UPDATE public.users SET settings_json =
            jsonb_set(COALESCE(settings_json, '{}'::jsonb), '{track_assessments}', %s::jsonb)
            WHERE id = %s""", (json.dumps(records), user_id))

    def submit(self, user_id, request_id, spec, responses, modality='written', assistance='none'):
        request_id = _request_id(request_id)
        if modality not in {'written', 'oral'} or assistance not in {'none', 'notes', 'help'}:
            raise ValueError("Choose a valid response mode and assistance declaration.")
        payload = {**_identity(spec), 'responses': _responses(responses, modality),
                   'modality': modality, 'assistance': assistance}
        with self.conn.transaction(), self.conn.cursor() as cur:
            records = self._locked(cur, user_id)
            previous = next((r for r in records if r.get('id') == request_id), None)
            if previous:
                if not verify_record(previous, str(user_id)):
                    raise AssessmentConflictError("Stored assessment integrity could not be verified; contact the operator.")
                if any(previous.get(k) != v for k, v in payload.items()):
                    raise AssessmentConflictError("This submission token already saved different answers.")
                return previous
            if len(records) >= MAX_SUBMISSIONS:
                raise AssessmentHistoryFullError("Assessment history is full. Your draft has not been submitted; contact the operator.")
            record = sign_record({'id': request_id, 'user_id': str(user_id), **payload,
                                  'submitted_at': _now(), 'state': 'pending'})
            records.append(record)
            self._write(cur, user_id, records)
        cache.invalidate(f'user_settings:{user_id}')
        return record

    def review(self, user_id, assessment_id, reviewer_id, spec, scores, evidence, practical_passed):
        assessment_id = _request_id(assessment_id)
        practical = _practical(practical_passed)
        if (not isinstance(evidence, dict) or len(evidence) > 20
                or any(not isinstance(text, str) or not text.strip() or len(text) > 2000
                       for text in evidence.values())):
            raise ValueError("Each criterion needs an exact excerpt, up to 2000 characters.")
        evidence = {key: text.strip() for key, text in evidence.items()}
        reviewer_id = reviewer_id.strip() if isinstance(reviewer_id, str) else reviewer_id
        with self.conn.transaction(), self.conn.cursor() as cur:
            records = self._locked(cur, user_id)
            record = next((r for r in records if r.get('id') == assessment_id), None)
            if record is None:
                raise ValueError("Assessment not found for this user.")
            if not verify_record(record, str(user_id)):
                raise AssessmentConflictError("Stored assessment integrity could not be verified; contact the operator.")
            if any(record.get(k) != v for k, v in _identity(spec).items()):
                raise AssessmentConflictError("Assessment version has changed; submit the current exam.")
            if record.get('state') == 'reviewed':
                old = record.get('review', {})
                if (all(old.get(k) == v for k, v in {'reviewer_id': reviewer_id, 'scores': scores, 'evidence': evidence}.items())
                        and record.get('practical_passed', {}).get('verified_slugs', []) == practical.get('verified_slugs', [])):
                    return record
                raise AssessmentConflictError("This assessment already has a different review.")
            if record.get('state') != 'pending':
                raise AssessmentConflictError("This assessment is not pending review.")
            if any(text not in record['responses']['answers'] for text in evidence.values()):
                raise ValueError("Each criterion needs an exact excerpt from the submitted answer, up to 2000 characters.")
            from ..services.track_exams import evaluate_review
            review = evaluate_review(spec, scores, evidence, reviewer_id)
            record.update(state='reviewed', review={**review, 'reviewed_at': _now()}, practical_passed=practical)
            record.update(sign_record(record))
            self._write(cur, user_id, records)
        cache.invalidate(f'user_settings:{user_id}')
        return record
