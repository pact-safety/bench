"""Tests for app.runners.python_runner split hidden/user outcomes."""

from __future__ import annotations

from app.runners.python_runner import run_python_tests


def test_hidden_pass_and_user_pass_marks_both_true():
    result = run_python_tests(
        submission="def add_one(x):\n    return x + 1\n",
        tests="assert add_one(1) == 2\n",
        timeout=5,
        user_tests="assert add_one(0) == 1\n",
    )

    assert result.hidden_passed is True
    assert result.user_passed is True
    assert result.passed is True


def test_hidden_pass_and_user_fail_marks_hidden_true_user_false():
    result = run_python_tests(
        submission="def add_one(x):\n    return x + 1\n",
        tests="assert add_one(1) == 2\n",
        timeout=5,
        user_tests="assert add_one(0) == 9\n",
    )

    assert result.hidden_passed is True
    assert result.user_passed is False
    assert result.passed is False


def test_hidden_fail_and_user_pass_marks_hidden_false_user_true():
    result = run_python_tests(
        submission="def add_one(x):\n    return x\n",
        tests="assert add_one(1) == 2\n",
        timeout=5,
        user_tests="assert add_one(0) == 0\n",
    )

    assert result.hidden_passed is False
    assert result.user_passed is True
    assert result.passed is False
