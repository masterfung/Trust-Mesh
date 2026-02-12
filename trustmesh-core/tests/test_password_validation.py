"""Tests for password complexity validation in UserCreate schema."""

import pytest
from pydantic import ValidationError

from src.schemas import UserCreate


def _make_user(**overrides):
    defaults = {
        "username": "testuser",
        "display_name": "Test User",
        "bio": "test",
        "password": "ValidPassword1!xx",  # 17 chars, meets all requirements
    }
    defaults.update(overrides)
    return UserCreate(**defaults)


def test_valid_password_accepted():
    user = _make_user(password="MySecurePass123!")
    assert user.password == "MySecurePass123!"


def test_valid_password_with_various_special_chars():
    for char in ["!", "@", "#", "$", "%", "^", "&", "*", "-", "_"]:
        pw = f"ValidPassword1{char}x"
        user = _make_user(password=pw)
        assert user.password == pw


def test_password_too_short():
    with pytest.raises(ValidationError) as exc_info:
        _make_user(password="Short1!")
    assert "at least 16 characters" in str(exc_info.value) or "min_length" in str(exc_info.value)


def test_password_no_uppercase():
    with pytest.raises(ValidationError) as exc_info:
        _make_user(password="nouppercase12345!")
    assert "uppercase" in str(exc_info.value)


def test_password_no_lowercase():
    with pytest.raises(ValidationError) as exc_info:
        _make_user(password="NOLOWERCASE12345!")
    assert "lowercase" in str(exc_info.value)


def test_password_no_digit():
    with pytest.raises(ValidationError) as exc_info:
        _make_user(password="NoDigitsHereAtAll!")
    assert "digit" in str(exc_info.value)


def test_password_no_special_char():
    with pytest.raises(ValidationError) as exc_info:
        _make_user(password="NoSpecialChars123")
    assert "special character" in str(exc_info.value)


def test_password_all_same_type():
    with pytest.raises(ValidationError):
        _make_user(password="aaaaaaaaaaaaaaaa")  # Only lowercase


def test_password_exactly_16_chars_valid():
    user = _make_user(password="ValidPass1234!ab")
    assert len(user.password) == 16


def test_password_max_length():
    # 128 chars, meets complexity
    pw = "A" + "a" * 124 + "1!x"
    user = _make_user(password=pw)
    assert len(user.password) == 128


def test_password_exceeds_max_length():
    pw = "A" + "a" * 125 + "1!x"  # 129 chars
    with pytest.raises(ValidationError):
        _make_user(password=pw)


def test_demo_password_meets_requirements():
    """The demo password must pass validation."""
    user = _make_user(password="TrustMesh-demo-2026")
    assert user.password == "TrustMesh-demo-2026"
