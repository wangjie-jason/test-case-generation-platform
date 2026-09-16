from pydantic import BaseModel, Field


class UpsertLlmConfigRequest(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    # 空串表示「不改已有 key」；首次配置时服务端校验必填。
    api_key: str = Field(default="", max_length=300)
    model: str = Field(min_length=1, max_length=120)


class TestLlmConfigRequest(BaseModel):
    # 支持「先测后存」：任一字段非空就按表单值测；全空则测已保存配置/系统兜底。
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=120)
