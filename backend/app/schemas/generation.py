from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    kb_ids: list[str] = Field(default_factory=list)
    requirement_text: str = Field(..., min_length=1)
    batch_name: str | None = None
    max_tokens: int = Field(default=4096, ge=100, le=16384)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)


class GenerateResponse(BaseModel):
    cases: list[dict]
    knowledge_used: dict
    knowledge_matches: dict[str, list[dict]] = Field(default_factory=dict)
    validation_warnings: list[dict] | None = None
