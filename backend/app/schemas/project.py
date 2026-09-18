from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    # 团队库（默认，全员可见引用，改删限创建者/管理员）或个人库（仅本人可见）。
    visibility: Literal["team", "personal"] = "team"

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("名称不能为空")
        return v


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    # 可见性仅创建者/管理员可改；不传保持原值。
    visibility: Literal["team", "personal"] | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("名称不能为空")
        return v


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: str | None
    owner_id: str
    visibility: str
    # 建库者用户名（团队库卡片上展示"谁建的"）。
    owner_name: str | None = None
    # 当前请求者是否可改/删（服务端按 owner/admin 算好，前端只据此显隐）。
    can_manage: bool = False
    created_at: datetime
    updated_at: datetime
