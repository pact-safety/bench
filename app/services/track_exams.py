"""Pilot human-reviewed assessments; scores never come from an AI verdict."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json

from app.services.track_checks import questions_version
from app.services.tracks import Track, section_at


def _criterion(identifier, label, description, essential, anchors):
    return dict(id=identifier, label=label, description=description,
                essential=essential, anchors=dict(enumerate(anchors)))


def spec_for_section(track: Track, idx: int) -> dict | None:
    """Return a fresh rubric for a supported section, bound to its current source."""
    if type(idx) is not int or section_at(track, idx) is None:
        return None
    key = (track.slug, idx)
    if key == ('ml4good-prework-fall-2026', 5):
        questions = [
            dict(id='capability', kind='explanation', prompt='Explain a capability trend from the Atlas chapter. Distinguish the observed evidence from the broader claim, and explain how compute, data, and algorithms bear on the trend.'),
            dict(id='forecast', kind='application', prompt='Fresh application: a hypothetical lab reports twice the score on one benchmark after using four times the training compute. A commentator predicts that its system will automate every job next year. Assess what follows from the reported result, identify missing evidence, and propose a discriminating evaluation. Do not assume facts beyond this scenario.'),
            dict(id='uncertainty', kind='explanation', prompt='Contrast two development or takeoff scenarios. State an assumption and an observation that would change your assessment, and identify an unresolved question for discussion.'),
        ]
        criteria = [
            _criterion('evidence', 'Capability evidence', 'Distinguishes a measured capability from claims beyond the measurement.', True, (
                'No relevant evidence or explanation.', 'Names a claim but confuses it with evidence.',
                'Identifies evidence but leaves an important inference unsupported.',
                'Explains a relevant measurement and a meaningful limit on its interpretation.',
                'Also compares plausible interpretations and explains what evidence distinguishes them.')),
            _criterion('scaling', 'Scaling and assumptions', 'Explains how compute, data, and algorithmic changes inform a capability trend.', True, (
                'No relevant account of scaling.', 'Lists factors without explaining their roles.',
                'Explains some roles but treats extrapolation as certain or misses a key assumption.',
                'Connects the factors to the trend and identifies a material extrapolation assumption.',
                'Also explains how a change in that assumption could alter the forecast.')),
            _criterion('application', 'Fresh application', 'Evaluates the hypothetical benchmark claim and proposes informative additional evidence.', True, (
                'Does not address the hypothetical claim.', 'Accepts or rejects the claim without reasoning.',
                'Identifies a limitation but proposes evidence that does not resolve it.',
                'Separates supported and unsupported inferences and proposes a relevant discriminating evaluation.',
                'Also explains how alternative evaluation outcomes would change the conclusion.')),
            _criterion('uncertainty', 'Calibrated uncertainty', 'Compares scenarios and identifies a substantive unresolved question.', False, (
                'No scenario comparison or uncertainty.', 'Names uncertainty without a specific assumption.',
                'Names scenarios and an assumption but no meaningful update condition.',
                'Compares scenarios, states an update condition, and poses a relevant question.',
                'Also explains why the update discriminates between scenarios without false precision.')),
        ]
    elif key == ('arena_3', 0):
        questions = [
            dict(id='axes', kind='explanation', prompt='Explain how named axes describe a tensor computation. Distinguish rearranging, reducing, repeating, and contracting, using a small example and stating each input and output shape.'),
            dict(id='contraction', kind='application', prompt='Fresh application: X has shape (batch, time, features) and W has shape (heads, features, outputs). Define a result that contracts their shared feature dimension while retaining each batch, time, head, and output position. Write a loop-free einsum expression, predict its shape, and explain every index. Use unequal dimension sizes in your check.'),
            dict(id='validation', kind='application', prompt='Choose tiny numeric tensors for that computation and compare the loop-free result with an explicit loop calculation. Then consider an accidental interchange of two equal-sized axes: explain why a shape-only test might miss it and propose a test that would reveal it.'),
        ]
        criteria = [
            _criterion('axes', 'Axis meanings and shapes', 'Binds axis names to dimensions and distinguishes tensor operations.', True, (
                'No coherent axis or shape explanation.', 'Names dimensions but confuses their meanings.',
                'Explains some operations but leaves an important axis or shape ambiguous.',
                'Correctly distinguishes operations and explains all axes and shapes in the example.',
                'Also identifies dimension constraints and explains how a changed size affects validity.')),
            _criterion('contraction', 'Loop-free contraction', 'Expresses the requested computation and identifies retained and summed indices.', True, (
                'No relevant loop-free expression.', 'Expression does not represent the requested contraction.',
                'Mostly relevant expression with an incorrect or unexplained retained or summed index.',
                'Correct expression, output shape, and explanation of every retained and summed index.',
                'Also explains its equivalence to a loop formulation and relevant dimension constraints.')),
            _criterion('application', 'Numerical application', 'Applies the expression to a fresh small case and compares against a loop reference.', True, (
                'No concrete application.', 'Provides a case without a meaningful comparison.',
                'Attempts a comparison but uses a degenerate case or leaves discrepancies unresolved.',
                'Shows an informative tiny case and a correct comparison with a loop reference.',
                'Also uses a contrasting case to test a plausible alternative or indexing mistake.')),
            _criterion('validation', 'Detecting axis errors', 'Explains the limits of shape-only checks and proposes a targeted value-based test.', False, (
                'No error-detection reasoning.', 'Relies on output shape alone.',
                'Recognizes the risk but proposes an insensitive test.',
                'Explains the equal-size axis risk and proposes a test that distinguishes meanings.',
                'Also explains the expected failure signature and why the test isolates that error.')),
        ]
    else:
        return None
    section = section_at(track, idx)
    spec = dict(id=f'{track.slug}:{idx}:human-pilot', track_slug=track.slug, section_idx=idx,
                questions=questions, criteria=criteria, threshold=80,
                practical_required=list(section.cold_checkpoint),
                policy='Provisional pilot: at least 80% overall and 3/4 on every essential criterion. Human review required; this is not a validated certification.')
    content = dict(spec, check_source=questions_version(track, idx))
    spec['version'] = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    return spec


def evaluate_review(spec: dict, scores: dict, evidence: dict, reviewer_id: str) -> dict:
    """Compute a rubric verdict from an authenticated human review's evidence."""
    ids = {criterion['id'] for criterion in spec['criteria']}
    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        raise ValueError('A human reviewer identity is required.')
    if not isinstance(scores, dict) or set(scores) != ids:
        raise ValueError('Supply exactly one score for every criterion.')
    if any(type(score) is not int or not 0 <= score <= 4 for score in scores.values()):
        raise ValueError('Criterion scores must be integers from 0 to 4.')
    if not isinstance(evidence, dict) or set(evidence) != ids or any(
        not isinstance(value, str) or not value.strip() for value in evidence.values()
    ):
        raise ValueError('Supply nonempty evidence for every criterion.')
    total, maximum = sum(scores.values()), 4 * len(ids)
    essential_passed = all(scores[c['id']] >= 3 for c in spec['criteria'] if c['essential'])
    approved = total * 100 >= spec['threshold'] * maximum and essential_passed
    return dict(reviewer_id=reviewer_id.strip(), review_type='human', scores=dict(scores),
                evidence={key: value.strip() for key, value in evidence.items()},
                total_score=total, max_score=maximum, percentage=total * 100 / maximum,
                essential_passed=essential_passed, verdict='approved' if approved else 'not_approved')


def _timestamp(value):
    if not isinstance(value, str) or 'T' not in value:
        return False
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return False
    return True


def valid_exemptions(track: Track, records: list, user_id: str | None = None) -> set[int]:
    """Validate signed reviews for the expected learner and current rubric."""
    from app.services.track_assessment_integrity import verify_record

    valid = set()
    if not isinstance(user_id, str) or not user_id.strip() or not isinstance(records, list):
        return valid
    for record in records:
        if not isinstance(record, dict) or not verify_record(record, user_id):
            continue
        if record.get('track_slug') != track.slug:
            continue
        idx = record.get('section_idx')
        spec = spec_for_section(track, idx)
        if not spec or record.get('state') != 'reviewed' or record.get('assistance') != 'none':
            continue
        if record.get('spec_id') != spec['id'] or record.get('spec_version') != spec['version']:
            continue
        responses = record.get('responses')
        if not isinstance(responses, dict) or not isinstance(responses.get('answers'), str) or not responses['answers'].strip():
            continue
        if record.get('modality') not in ('written', 'oral'):
            continue
        if record['modality'] == 'oral' and responses.get('transcript_confirmed') is not True:
            continue
        review = record.get('review')
        if not isinstance(review, dict) or review.get('review_type') != 'human' or review.get('verdict') != 'approved':
            continue
        try:
            computed = evaluate_review(spec, review.get('scores'), review.get('evidence'), review.get('reviewer_id'))
        except ValueError:
            continue
        if computed['verdict'] != 'approved':
            continue
        if spec['practical_required']:
            practical = record.get('practical_passed')
            if not isinstance(practical, dict) or not _timestamp(practical.get('checked_at')):
                continue
            slugs = practical.get('verified_slugs')
            if not isinstance(slugs, list) or any(not isinstance(slug, str) for slug in slugs):
                continue
            if not set(spec['practical_required']).issubset(slugs):
                continue
        valid.add(idx)
    return valid
