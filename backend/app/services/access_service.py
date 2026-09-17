"""知识库可见性与写权限的统一判定。

- 可见：本人的个人库 + 所有团队库（管理员对个人库不特殊放行，严格"仅本人可见"）。
- 可管理（改/删/写子资源）：库的 owner 或管理员。
生成/clarify 时请求体自报的 kb_ids 必须先收敛到当前用户可见集合，否则越界 400。
"""
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_base import KnowledgeBase
from app.models.user import User

TEAM = "team"
PERSONAL = "personal"


def can_manage(kb: KnowledgeBase, user: User) -> bool:
    return user.is_admin or kb.owner_id == user.id


async def visible_kb_ids(db: AsyncSession, user: User) -> list[str]:
    rows = await db.scalars(
        select(KnowledgeBase.id).where(
            or_(KnowledgeBase.owner_id == user.id, KnowledgeBase.visibility == TEAM)
        )
    )
    return list(rows)


async def resolve_kb_ids(db: AsyncSession, user: User, requested: list[str] | None) -> list[str]:
    """把请求自报的 kb_ids 收敛到可见集合。

    空（不指定）= 用全部可见库；指定了不可见/不存在的 id 一律 400，避免通过
    自报 kb_id 检索他人个人库。
    """
    visible = await visible_kb_ids(db, user)
    if not requested:
        return visible
    visible_set = set(visible)
    forbidden = [k for k in requested if k not in visible_set]
    if forbidden:
        raise HTTPException(status_code=400, detail="存在无权访问或不存在的知识库")
    return requested


async def get_kb_or_404(
    db: AsyncSession, kb_id: str, user: User, require_manage: bool = False
) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    # 个人库严格仅 owner 可见——管理员也看不到他人个人库内容（能管团队库即可）。
    visible = kb is not None and (kb.owner_id == user.id or kb.visibility == TEAM)
    if kb is None or not visible:
        # 不可见与不存在返回同一句话，不泄露他人个人库的存在性。
        raise HTTPException(404, "知识库不存在")
    if require_manage and not can_manage(kb, user):
        raise HTTPException(403, "只有创建者或管理员可以修改该团队知识库")
    return kb
