"""Password hashing, session tokens, TOTP (MFA), field encryption and rate limiting."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings

_hasher = PasswordHasher()
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Please use at least {MIN_PASSWORD_LENGTH} characters."
    if password.lower() in {"password123", "1234567890", "qwertyuiop"}:
        return "That password is too easy to guess."
    return None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Only this keyed hash is stored, so a database leak does not expose sessions."""
    return hmac.new(get_settings().secret_key.encode(), token.encode(), hashlib.sha256).hexdigest()


def _fernet() -> Fernet:
    key = get_settings().encryption_key.encode()
    try:
        return Fernet(key)
    except ValueError:
        # Accept any passphrase by deriving a key from it.
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key).digest()))


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=get_settings().app_name)


def verify_totp(secret: str, code: str) -> bool:
    code = "".join(ch for ch in code if ch.isdigit())
    return len(code) == 6 and pyotp.TOTP(secret).verify(code, valid_window=1)


def new_recovery_codes(n: int = 8) -> list[str]:
    return [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(n)]


def recovery_hash(code: str) -> str:
    return token_hash("recovery:" + code.strip().lower())


class RateLimiter:
    """Sliding-window limiter kept in memory (one process). For several API
    instances put a shared limiter (for example at the reverse proxy) in front."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()
