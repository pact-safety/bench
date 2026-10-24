from unittest.mock import MagicMock

import pytest

from app.repositories.feedback_repository import FeedbackRepository


def repository(*rows):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = rows
    return FeedbackRepository(conn), conn, cur


def test_request_locks_owner_before_lookup_and_insert():
    repo, conn, cur = repository({'id': 'owner'}, None, {'id': 12})
    assert repo.request_track('owner', 'mechinterp', 'Mechanistic interpretability') == 12
    calls = [call.args for call in cur.execute.call_args_list]
    assert 'public.users' in calls[0][0] and 'FOR UPDATE' in calls[0][0]
    assert calls[0][1] == ('owner',)
    assert 'user_id = %s AND url = %s AND body = %s' in calls[1][0]
    assert calls[1][1] == ('owner', '/tracks/mechinterp#request-track', 'Track access request: mechinterp')
    assert 'INSERT INTO feedback' in calls[2][0]
    assert calls[2][1] == ('owner', '/tracks/mechinterp#request-track',
        'Mechanistic interpretability', 'Track access request: mechinterp')
    conn.transaction.assert_called_once()
    conn.commit.assert_not_called()


def test_existing_request_returns_same_id_without_reopening_or_rewriting():
    repo, _, cur = repository({'id': 'owner'}, {'id': 7})
    assert repo.request_track('owner', 'mechinterp', 'Renamed curriculum') == 7
    assert cur.execute.call_count == 2
    assert all('UPDATE feedback' not in call.args[0] and 'INSERT' not in call.args[0]
        for call in cur.execute.call_args_list)
    assert 'status' not in cur.execute.call_args.args[0]


def test_missing_user_cannot_create_feedback():
    repo, _, cur = repository(None)
    with pytest.raises(ValueError, match='user'):
        repo.request_track('missing', 'mechinterp', 'Track')
    assert cur.execute.call_count == 1


@pytest.mark.parametrize('slug,title', [
    ('', 'Track'), ('../escape', 'Track'), ('bad?query', 'Track'), ('x' * 101, 'Track'),
    ('mats', ''), ('mats', ' '), ('mats', 'x' * 201),
])
def test_request_values_are_bounded_before_transaction(slug, title):
    repo, conn, _ = repository()
    with pytest.raises(ValueError):
        repo.request_track('owner', slug, title)
    conn.transaction.assert_not_called()
