"""Security primitives: password hashing (argon2) + JWT create/verify.

This module is the auth swap-point (decision #10): routers depend only on these
functions, so replacing backend-issued JWTs with Firebase ID tokens later means
re-implementing this module, not touching the API layer.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from pwdlib import PasswordHash

from app.core.config import settings
from app.core.exceptions import CredentialsError

_password_hasher = PasswordHash.recommended()  # argon2

TokenType = Literal["access", "refresh"]


# --- Passwords (decision #3: pwdlib + argon2) -------------------------------


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _password_hasher.verify(password, hashed)


# --- JWTs (decision #3: access 30 min, refresh 7 days) ----------------------


def _create_token(subject: str, token_type: TokenType, expires_delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: int) -> str:
    return _create_token(
        str(user_id), "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(user_id: int) -> str:
    return _create_token(
        str(user_id), "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )


def decode_token(token: str, expected_type: TokenType) -> int:
    """Decode + validate a JWT, returning the user id.

    Raises CredentialsError (401) on invalid/expired tokens or type mismatch.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise CredentialsError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise CredentialsError("Invalid token") from exc

    if payload.get("type") != expected_type:
        raise CredentialsError(f"Expected a {expected_type} token")

    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CredentialsError("Malformed token subject") from exc
