from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    kb_ids: list[str] = Field(default_factory=list)
    requirement_text: str = Field(..., min_length=1)
    batch_name: str | None = None
    # 归属者标识：前端 localStorage 中的匿名 client_id，用于多人/多浏览器任务隔离。
    # 将来接入登录后可改由服务端从登录态解析，字段本身保持中立。
    client_id: str | None = None
    max_tokens: int = Field(default=4096, ge=100, le=16384)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
