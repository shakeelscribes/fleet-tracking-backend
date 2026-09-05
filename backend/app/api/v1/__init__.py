"""v1 route aggregation (decision #12)."""

from fastapi import APIRouter

from app.api.v1 import auth

v1_router = APIRouter()
v1_router.include_router(auth.router)
