from datetime import datetime

from pydantic import BaseModel


class KnowledgeBaseCreate(BaseModel):
    name: str
    description: str | None = None


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
