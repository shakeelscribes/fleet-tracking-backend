"""Authentication business logic (decision #3, #10).

The only module that knows how credentials become tokens; the Firebase swap-point
lives in core.security, this module composes it with the DB.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import CredentialsError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models import User
from app.schemas.auth import TokenPair


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    """Verify credentials; identical error for unknown email and wrong password
    (prevents user enumeration)."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password):
        raise CredentialsError("Incorrect email or password")
    return user


def issue_token_pair(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


async def refresh_token_pair(db: AsyncSession, refresh_token: str) -> TokenPair:
    """Exchange a valid refresh token for a fresh token pair (decision #3)."""
    user_id = decode_token(refresh_token, expected_type="refresh")
    user = await db.get(User, user_id)
    if user is None:
        raise CredentialsError("User no longer exists")
    return issue_token_pair(user)
