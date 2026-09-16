from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.routers.deps import get_current_admin
from app.schemas.user import (
    AdminCreateUserRequest,
    AdminUpdateUserRequest,
    ResetPasswordRequest,
    UserResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/admin/users", tags=["用户管理"], dependencies=[Depends(get_current_admin)])


async def _active_admin_count(db: AsyncSession) -> int:
    return await db.scalar(
        select(func.count()).select_from(User).where(User.is_admin.is_(True), User.is_active.is_(True))
    )


@router.get("", response_model=list[UserResponse])
async def list_users(db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(User).order_by(User.created_at))
    return list(rows)


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(body: AdminCreateUserRequest, db: AsyncSession = Depends(get_db)):
    exists = await db.scalar(select(User).where(User.username == body.username))
    if exists is not None:
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = User(
        username=body.username,
        password_hash=auth_service.hash_password(body.password),
        display_name=body.display_name,
        is_admin=body.is_admin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: AdminUpdateUserRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    data = body.model_dump(exclude_unset=True)
    # 不允许对自己执行停用或降级，避免误操作把自己锁在门外。
    if user.id == admin.id and (data.get("is_active") is False or data.get("is_admin") is False):
        raise HTTPException(status_code=400, detail="不能停用或降级自己")
    # 任何时候都要至少保留一个活跃管理员。
    will_lose_admin = (
        (data.get("is_active") is False and user.is_admin)
        or (data.get("is_admin") is False and user.is_active)
    )
    if will_lose_admin and await _active_admin_count(db) <= 1:
        raise HTTPException(status_code=400, detail="至少保留一个活跃管理员")

    for field, value in data.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = auth_service.hash_password(body.new_password)
    await db.commit()
    return {"message": "密码已重置"}
