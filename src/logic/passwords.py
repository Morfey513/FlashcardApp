"""Password hashing shared by JSON and PostgreSQL account repositories."""

import hashlib
import hmac
import secrets


class PasswordHasher:
    """PBKDF2 helper preserving the application's existing hash format."""

    HASH_NAME = "pbkdf2_sha256"
    HASH_ITERATIONS = 210_000

    @classmethod
    def hash(cls, password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("ascii"),
            cls.HASH_ITERATIONS,
        ).hex()
        return f"{cls.HASH_NAME}${cls.HASH_ITERATIONS}${salt}${digest}"

    @classmethod
    def verify(cls, password: str, stored_value: str) -> bool:
        try:
            algorithm, iterations, salt, expected = stored_value.split("$", 3)
            if algorithm != cls.HASH_NAME:
                return False
            actual = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt.encode("ascii"),
                int(iterations),
            ).hex()
            return hmac.compare_digest(actual, expected)
        except (AttributeError, TypeError, ValueError):
            return False
