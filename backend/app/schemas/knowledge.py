from datetime import datetime

from pydantic import BaseModel


# ── 字段字典 ──

class FieldDictCreate(BaseModel):
    field_name: str
    display_name: str
    data_source: str | None = None
    data_type: str = "str"
    enum_values: str | None = None
    description: str | None = None


class FieldDictUpdate(BaseModel):
    field_name: str | None = None
    display_name: str | None = None
    data_source: str | None = None
    data_type: str | None = None
    enum_values: str | None = None
    description: str | None = None


class FieldDictResponse(BaseModel):
    id: str
    kb_id: str
    field_name: str
    display_name: str
    data_source: str | None
    data_type: str
    enum_values: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 业务规则 ──

class BusinessRuleCreate(BaseModel):
    rule_name: str
    rule_type: str = "hard"
    expression: str
    description: str | None = None
    source: str | None = None


class BusinessRuleUpdate(BaseModel):
    rule_name: str | None = None
    rule_type: str | None = None
    expression: str | None = None
    description: str | None = None
    source: str | None = None


class BusinessRuleResponse(BaseModel):
    id: str
    kb_id: str
    rule_name: str
    rule_type: str
    expression: str
    description: str | None
    source: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 状态机 ──

class StateMachineCreate(BaseModel):
    entity: str
    from_state: str
    to_state: str
    condition: str | None = None


class StateMachineUpdate(BaseModel):
    entity: str | None = None
    from_state: str | None = None
    to_state: str | None = None
    condition: str | None = None


class StateMachineResponse(BaseModel):
    id: str
    kb_id: str
    entity: str
    from_state: str
    to_state: str
    condition: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 术语映射 ──

class TermMappingCreate(BaseModel):
    ui_term: str
    tech_field: str
    mapping_desc: str | None = None


class TermMappingUpdate(BaseModel):
    ui_term: str | None = None
    tech_field: str | None = None
    mapping_desc: str | None = None


class TermMappingResponse(BaseModel):
    id: str
    kb_id: str
    ui_term: str
    tech_field: str
    mapping_desc: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── PRD 文档 ──

class PrdDocumentResponse(BaseModel):
    id: str
    kb_id: str
    filename: str
    file_format: str
    raw_text: str
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 缺陷记录 ──

class DefectRecordCreate(BaseModel):
    title: str
    severity: str = "minor"
    root_cause: str | None = None
    description: str
    related_case: str | None = None
    occurred_at: str | None = None


class DefectRecordUpdate(BaseModel):
    title: str | None = None
    severity: str | None = None
    root_cause: str | None = None
    description: str | None = None
    related_case: str | None = None
    occurred_at: str | None = None


class DefectRecordResponse(BaseModel):
    id: str
    kb_id: str
    title: str
    severity: str
    root_cause: str | None
    description: str
    related_case: str | None
    occurred_at: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
