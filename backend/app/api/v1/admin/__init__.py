"""Admin sub-routers, gated as one unit (decision #7)."""

from fastapi import APIRouter, Depends

from app.api.v1.admin import routes, users, vehicles
from app.core.deps import require_admin

admin_router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
admin_router.include_router(routes.router)
admin_router.include_router(vehicles.router)
admin_router.include_router(users.router)
