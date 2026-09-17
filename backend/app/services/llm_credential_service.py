"""用户个人大模型凭据的读写与两级解析。

解析顺序（resolve_credentials）：用户个人配置优先（花自己的额度）→ 否则系统兜底
模型（settings.LLM_API_KEY，公司出一份默认额度）→ 两者都没有才抛
CredentialNotConfiguredError。个人 key 调用失败时**不**自动降级到兜底，避免用户
不知道自己配错、公司额度被悄悄花掉。
"""
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import UserLlmConfig
from app.services import crypto_service
from app.utils.llm_credentials import (
    CredentialNotConfiguredError,
    LLMCredentials,
)

SOURCE_USER = "user"
SOURCE_SYSTEM = "system"


def system_credentials() -> LLMCredentials | None:
    """配置了全局兜底 key 时返回其凭据，否则 None。"""
    if not settings.LLM_API_KEY.strip():
        return None
    return LLMCredentials(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        model=settings.LLM_MODEL,
        source=SOURCE_SYSTEM,
    ).normalized()


async def get_personal_row(db: AsyncSession, user_id: str) -> UserLlmConfig | None:
    return await db.get(UserLlmConfig, user_id)


async def resolve_credentials(db: AsyncSession, user_id: str) -> LLMCredentials:
    """个人配置 → 系统兜底 → 报错。生成/clarify 入口调用。"""
    row = await get_personal_row(db, user_id)
    if row is not None:
        return LLMCredentials(
            base_url=row.base_url,
            api_key=crypto_service.decrypt(row.api_key_encrypted),
            model=row.model,
            source=SOURCE_USER,
        ).normalized()
    fallback = system_credentials()
    if fallback is not None:
        return fallback
    raise CredentialNotConfiguredError(
        "尚未配置大模型凭据，也没有可用的系统默认模型，请先到「设置」页填写"
    )


async def resolve_credentials_optional(db: AsyncSession, user_id: str) -> LLMCredentials | None:
    """同 resolve，但都没配置时返回 None（图片 OCR 等不该被凭据挡住的场景）。"""
    try:
        return await resolve_credentials(db, user_id)
    except CredentialNotConfiguredError:
        return None


async def get_config_dto(db: AsyncSession, user_id: str) -> dict:
    """设置页回显：个人配置（key 只给脱敏串）+ 系统兜底是否可用。"""
    row = await get_personal_row(db, user_id)
    fallback = system_credentials()
    return {
        "configured": row is not None,
        "base_url": row.base_url if row else None,
        "model": row.model if row else None,
        "api_key_masked": row.api_key_masked if row else None,
        "updated_at": str(row.updated_at) if row else None,
        "fallback_available": fallback is not None,
        "fallback_model": fallback.model if fallback else None,
    }


async def upsert_config(
    db: AsyncSession,
    user_id: str,
    *,
    base_url: str,
    api_key: str | None,
    model: str,
) -> UserLlmConfig:
    """新增或更新个人凭据。api_key 为 None/空串表示「不改」（编辑 base_url/model
    时不必重录 key），首次配置时必填。"""
    base_url = base_url.strip()
    model = model.strip()
    row = await get_personal_row(db, user_id)
    if row is None:
        if not api_key or not api_key.strip():
            raise ValueError("首次配置必须填写 API Key")
        row = UserLlmConfig(user_id=user_id)
        db.add(row)
    row.base_url = base_url.rstrip("/")
    row.model = model
    if api_key and api_key.strip():
        key = api_key.strip()
        row.api_key_encrypted = crypto_service.encrypt(key)
        row.api_key_masked = crypto_service.mask_api_key(key)
    await db.commit()
    await db.refresh(row)
    return row


async def clear_config(db: AsyncSession, user_id: str) -> None:
    """删除个人配置，回到系统兜底模型。"""
    row = await get_personal_row(db, user_id)
    if row is not None:
        await db.delete(row)
        await db.commit()


async def probe_credentials(creds: LLMCredentials) -> dict:
    """用凭据发一次最小 chat 请求验证连通性，返回 {ok, latency_ms, message}。"""
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            resp = await client.post(
                f"{creds.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {creds.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": creds.model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 8,
                },
            )
    except httpx.RequestError as exc:
        return {"ok": False, "latency_ms": None,
                "message": f"无法连接 {creds.base_url}（{type(exc).__name__}），请检查 base_url 与网络"}
    latency = round((time.monotonic() - started) * 1000)
    detail = ""
    try:
        detail = (resp.json().get("error") or {}).get("message", "") or ""
    except Exception:  # noqa: BLE001 错误体不是 JSON 也无妨
        pass
    suffix = f"：{detail}" if detail else ""
    if resp.status_code == 200:
        return {"ok": True, "latency_ms": latency, "message": "连接成功"}
    if resp.status_code in (401, 403):
        return {"ok": False, "latency_ms": latency, "message": "API Key 无效或无权限（401/403）"}
    if resp.status_code == 404:
        return {"ok": False, "latency_ms": latency,
                "message": "接口地址 404，请检查 base_url 是否指向 /chat/completions 的基址（通常以 /v1 结尾）"}
    if resp.status_code == 400:
        return {"ok": False, "latency_ms": latency, "message": f"请求被拒（400），模型名可能有误{suffix}"}
    if resp.status_code == 429:
        return {"ok": False, "latency_ms": latency, "message": "受限流（429）：额度或并发可能已达上限"}
    return {"ok": False, "latency_ms": latency, "message": f"服务返回 {resp.status_code}{suffix}"}
