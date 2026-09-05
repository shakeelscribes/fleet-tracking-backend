"""API route aggregation (decision #12)."""

from fastapi import APIRouter

api_router = APIRouter()


@api_router.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness probe for Docker healthchecks and Render."""
    return {"status": "ok"}
