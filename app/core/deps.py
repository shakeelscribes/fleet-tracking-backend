"""FastAPI dependencies: DB session, current user, admin gate (decisions #2, #10)."""

from collections.abc import AsyncIterator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CredentialsError, ForbiddenError
from app.core.security import decode_token
from app.db.session import async_session_factory
from app.models import User

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a database session per request."""
    async with async_session_factory() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the JWT bearer token to a User row (decision #10 swap-point)."""
    if credentials is None:
        raise CredentialsError("Not authenticated")

    user_id = decode_token(credentials.credentials, expected_type="access")

    user = await db.get(User, user_id)
    if user is None:
        raise CredentialsError("User no longer exists")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Admin gate for /admin/* routes (decision #7)."""
    if not user.is_admin:
        raise ForbiddenError("Admin privileges required")
    return user
