"""API route aggregation (decision #12): /api/v1/* + root-level system endpoints."""

from fastapi import APIRouter

from app.api.v1 import v1_router

api_router = APIRouter()
api_router.include_router(v1_router, prefix="/api/v1")


@api_router.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness probe for Docker healthchecks and Render."""
    return {"status": "ok"}
