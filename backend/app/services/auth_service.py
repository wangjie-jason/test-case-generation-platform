"""认证：bcrypt 口令哈希 + HS256 JWT 签发/解析。

设计取舍（内部工具求简）：
- 单个 access token、有效期 12 小时（一个工作日），不做 refresh token 与吊销名单，
  过期重新登录；登出纯前端丢弃 token。
- JWT claims 只放身份（sub/username），**不放 is_admin**——角色与停用状态每请求查库，
  管理员降级或停用账号在下一个请求立即生效，不等 token 过期。
"""
import datetime as dt
import logging

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
# bcrypt 只处理前 72 字节，schema 层已限制口令长度，这里再防御一次。
_BCRYPT_MAX_BYTES = 72


class TokenError(Exception):
    """token 缺失/过期/非法的统一异常。"""


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8")[:_BCRYPT_MAX_BYTES], password_hash.encode("utf-8")
        )
    except ValueError:
        # 库里的哈希格式非法时不要抛 500，按口令错误处理。
        return False


def create_access_token(user: User) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": user.id,
        "username": user.username,
        "iat": now,
        "exp": now + dt.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, ALGORITHM)


def decode_token(token: str) -> str:
    """返回 user_id；token 过期/非法一律抛 TokenError（由路由依赖转成 401）。"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("登录状态无效，请重新登录") from exc
    user_id = payload.get("sub")
    if not user_id:
        raise TokenError("登录状态无效，请重新登录")
    return user_id


async def ensure_admin(db: AsyncSession) -> None:
    """启动时确保 .env 配置的首个管理员存在：不存在则创建，已存在绝不改密。

    迁移 0003 已在全新库上建过该管理员，这里是不依赖 alembic 的双保险。
    """
    username = settings.ADMIN_USERNAME
    existing = await db.scalar(select(User).where(User.username == username))
    if existing is not None:
        return
    db.add(User(
        username=username,
        password_hash=hash_password(settings.ADMIN_PASSWORD),
        display_name="管理员",
        is_admin=True,
    ))
    await db.commit()
    logger.info("已创建首个管理员账号：%s", username)
