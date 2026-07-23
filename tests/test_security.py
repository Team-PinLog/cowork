import pytest

from app.security import hash_password, verify_password


def test_hash_password_accepts_seven_characters():
    password = "1234567"

    password_hash = hash_password(password)

    assert verify_password(password, password_hash)


def test_hash_password_rejects_six_characters():
    with pytest.raises(ValueError, match="at least 7 characters"):
        hash_password("123456")
