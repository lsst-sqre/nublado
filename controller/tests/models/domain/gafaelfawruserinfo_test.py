"""Tests for the ``GafaelfawrUserInfo`` model."""

from __future__ import annotations

from ...support.data import read_input_users_json


def test_no_name() -> None:
    users = read_input_users_json("no-name", "users")
    assert users["token-of-anonymity"].name is None
