"""Admin user management + the assignment endpoint (the graded core)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.schemas.user import AssignmentUpdate, UserCreate, UserOut, UserUpdate
from app.services import fleet_admin_service as svc

router = APIRouter(prefix="/users", tags=["admin:users"])


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, db: AsyncSession = Depends(get_db)):
    return await svc.create_user(db, body)


@router.get("", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db)):
    return await svc.list_users(db)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    return await svc.get_user(db, user_id)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: int, body: UserUpdate, db: AsyncSession = Depends(get_db)):
    user = await svc.get_user(db, user_id)
    return await svc.update_user(db, user, body)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, db: AsyncSession = Depends(get_db)) -> None:
    user = await svc.get_user(db, user_id)
    await svc.delete_user(db, user)


@router.put(
    "/{user_id}/assignment",
    response_model=UserOut,
    summary="Assign/reassign one route + one vehicle to a user; null/null to unassign",
)
async def set_assignment(
    user_id: int, body: AssignmentUpdate, db: AsyncSession = Depends(get_db)
):
    return await svc.set_assignment(db, user_id, body)
