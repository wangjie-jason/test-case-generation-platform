from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GenerateRequest(BaseModel):
    kb_ids: list[str] = Field(default_factory=list)
    requirement_text: str = Field(..., min_length=1)
    batch_name: str | None = None
    # 归属者标识：前端 localStorage 中的匿名 client_id，用于多人/多浏览器任务隔离。
    # 将来接入登录后可改由服务端从登录态解析，字段本身保持中立。
    client_id: str | None = None
    max_tokens: int = Field(default=4096, ge=100, le=16384)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)


class UpdateCaseRequest(BaseModel):
    """人工编辑用例的可更新字段。未提供的字段保持不变。"""

    title: str | None = Field(default=None, max_length=500)
    priority: str | None = Field(default=None, max_length=4)
    precondition: str | None = None
    steps: str | list[Any] | None = None
    expected_result: str | None = None


class CreateCaseRequest(BaseModel):
    batch_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=500)
    priority: str | None = Field(default=None, max_length=4)
    precondition: str | None = None
    steps: str | list[Any] | None = None
    expected_result: str | None = None
    prev_case_id: str | None = Field(default=None, max_length=36)
    next_case_id: str | None = Field(default=None, max_length=36)


class ReviewCaseRequest(BaseModel):
    status: Literal["approved", "rejected"]
    reject_reason: str | None = Field(default=None, max_length=50)


class ExportCase(BaseModel):
    """导出时保留生成器扩展字段，核心字段则保持有类型约束。"""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    title: str | None = None
    priority: str | None = None
    precondition: str | None = None
    steps: str | list[Any] | None = None
    expected_result: str | None = None


class ExportCasesRequest(BaseModel):
    cases: list[ExportCase] = Field(default_factory=list)
