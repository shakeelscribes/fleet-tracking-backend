"""Auth endpoints: login + refresh (decision #12)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.schemas.auth import LoginRequest, RefreshRequest, TokenPair
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenPair,
    status_code=status.HTTP_200_OK,
    summary="Authenticate with email + password, receive access + refresh tokens",
)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    user = await auth_service.authenticate_user(db, body.email, body.password)
    return auth_service.issue_token_pair(user)


@router.post(
    "/refresh",
    response_model=TokenPair,
    status_code=status.HTTP_200_OK,
    summary="Exchange a refresh token for a fresh token pair",
)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    return await auth_service.refresh_token_pair(db, body.refresh_token)
