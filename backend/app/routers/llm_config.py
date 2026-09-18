from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.routers.deps import get_current_user
from app.schemas.llm_config import TestLlmConfigRequest, UpsertLlmConfigRequest
from app.services import crypto_service, llm_credential_service as creds_svc
from app.utils.llm_credentials import LLMCredentials

router = APIRouter(prefix="/llm-config", tags=["大模型凭据"])


@router.get("")
async def get_config(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await creds_svc.get_config_dto(db, user.id)


@router.put("")
async def put_config(
    body: UpsertLlmConfigRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await creds_svc.upsert_config(
            db, user.id, base_url=body.base_url, api_key=body.api_key or None, model=body.model
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await creds_svc.get_config_dto(db, user.id)


@router.delete("")
async def clear_config(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await creds_svc.clear_config(db, user.id)
    return {"message": "已清除个人配置，将使用系统默认模型"}


@router.post("/test")
async def test_config(
    body: TestLlmConfigRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        form_fields = [body.base_url, body.api_key, body.model] if body else []
        if any(v and v.strip() for v in form_fields):
            # 先测后存：表单值优先，留空的字段回落到已保存的个人配置。
            row = await creds_svc.get_personal_row(db, user.id)
            base_url = (body.base_url or "").strip() or (row.base_url if row else "")
            model = (body.model or "").strip() or (row.model if row else "")
            api_key = (body.api_key or "").strip()
            if not api_key and row is not None:
                api_key = crypto_service.decrypt(row.api_key_encrypted)
            if not (base_url and model and api_key):
                raise HTTPException(status_code=400, detail="测试新配置需填齐 base_url、API Key、模型名")
            creds = LLMCredentials(base_url=base_url, api_key=api_key, model=model,
                                   source=creds_svc.SOURCE_USER).normalized()
        else:
            # 测当前实际生效的配置（个人配置或系统兜底）。
            creds = await creds_svc.resolve_credentials_optional(db, user.id)
            if creds is None:
                raise HTTPException(status_code=400, detail="尚未配置个人凭据，也没有系统默认模型")
    except crypto_service.CryptoError as exc:
        # 已保存的密文解不开（换过 Fernet 密钥/密文损坏）：引导重录，不抛 500。
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await creds_svc.probe_credentials(creds)
