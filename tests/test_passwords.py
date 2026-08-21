from src.logic.passwords import PasswordHasher


def test_password_hasher_round_trip_and_rejects_invalid_values():
    hashed = PasswordHasher.hash("correct horse battery staple")

    assert hashed.startswith("pbkdf2_sha256$210000$")
    assert PasswordHasher.verify("correct horse battery staple", hashed)
    assert not PasswordHasher.verify("wrong password", hashed)
    assert not PasswordHasher.verify("password", "not-a-valid-hash")
    assert not PasswordHasher.verify("password", None)
