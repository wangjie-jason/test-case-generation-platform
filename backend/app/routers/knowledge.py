import uuid as _uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.knowledge_base import KnowledgeBase
from app.schemas.knowledge import *
from app.schemas.project import KnowledgeBaseCreate, KnowledgeBaseResponse, KnowledgeBaseUpdate
from app.services.knowledge_service import KnowledgeService
from app.services.parser_service import ParserService
from app.services.excel_service import ExcelImportService
from app.services.indexing_service import IndexingService, PRD_COLLECTION, DEFECT_COLLECTION

router = APIRouter()
_kb = KnowledgeService()


# ── 知识库 ──

@router.post("/knowledge-bases", response_model=KnowledgeBaseResponse, status_code=201)
async def create_kb(data: KnowledgeBaseCreate, db: AsyncSession = Depends(get_db)):
    kb = KnowledgeBase(**data.model_dump())
    db.add(kb); await db.commit(); await db.refresh(kb); return kb

@router.get("/knowledge-bases", response_model=list[KnowledgeBaseResponse])
async def list_kbs(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    r = await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()))
    return r.scalars().all()

@router.get("/knowledge-bases/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_kb(kb_id: str, db: AsyncSession = Depends(get_db)):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb: raise HTTPException(404, "知识库不存在")
    return kb

@router.put("/knowledge-bases/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_kb(kb_id: str, data: KnowledgeBaseUpdate, db: AsyncSession = Depends(get_db)):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb: raise HTTPException(404, "知识库不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(kb, k, v)
    await db.commit(); await db.refresh(kb); return kb

@router.delete("/knowledge-bases/{kb_id}")
async def delete_kb(kb_id: str, db: AsyncSession = Depends(get_db)):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb: raise HTTPException(404, "知识库不存在")
    await db.delete(kb); await db.commit()
    return {"message": "删除成功"}

# ── 知识项 CRUD（按知识库隔离） ──

def _make_crud(prefix, list_fn, create_fn, get_fn, update_fn, delete_fn, create_schema, update_schema, response_schema):
    sub = APIRouter()
    @sub.get("", response_model=list[response_schema])
    async def list_items(kb_id: str, db: AsyncSession = Depends(get_db)): return await list_fn(db, kb_id)
    @sub.post("", response_model=response_schema, status_code=201)
    async def create_item(kb_id: str, data: create_schema, db: AsyncSession = Depends(get_db)): return await create_fn(db, kb_id, data.model_dump())
    @sub.put("/{item_id}", response_model=response_schema)
    async def update_item(kb_id: str, item_id: str, data: update_schema, db: AsyncSession = Depends(get_db)):
        item = await get_fn(db, item_id)
        if not item or item.kb_id != kb_id: raise HTTPException(404, "记录不存在")
        return await update_fn(db, item, data.model_dump(exclude_unset=True))
    @sub.delete("/{item_id}")
    async def delete_item(kb_id: str, item_id: str, db: AsyncSession = Depends(get_db)):
        item = await get_fn(db, item_id)
        if not item or item.kb_id != kb_id: raise HTTPException(404, "记录不存在")
        await delete_fn(db, item)
        return {"message": "删除成功"}
    return sub

router.include_router(_make_crud("field-dicts", _kb.list_field_dicts, _kb.create_field_dict, _kb.get_field_dict, _kb.update_field_dict, _kb.delete_field_dict, FieldDictCreate, FieldDictUpdate, FieldDictResponse), prefix="/knowledge-bases/{kb_id}/field-dicts")
router.include_router(_make_crud("business-rules", _kb.list_business_rules, _kb.create_business_rule, _kb.get_business_rule, _kb.update_business_rule, _kb.delete_business_rule, BusinessRuleCreate, BusinessRuleUpdate, BusinessRuleResponse), prefix="/knowledge-bases/{kb_id}/business-rules")
router.include_router(_make_crud("state-machines", _kb.list_state_machines, _kb.create_state_machine, _kb.get_state_machine, _kb.update_state_machine, _kb.delete_state_machine, StateMachineCreate, StateMachineUpdate, StateMachineResponse), prefix="/knowledge-bases/{kb_id}/state-machines")
router.include_router(_make_crud("term-mappings", _kb.list_term_mappings, _kb.create_term_mapping, _kb.get_term_mapping, _kb.update_term_mapping, _kb.delete_term_mapping, TermMappingCreate, TermMappingUpdate, TermMappingResponse), prefix="/knowledge-bases/{kb_id}/term-mappings")

# ── PRD 文档 ──

@router.get("/knowledge-bases/{kb_id}/prd-documents", response_model=list[PrdDocumentResponse])
async def list_prd_documents(kb_id: str, db: AsyncSession = Depends(get_db)): return await _kb.list_prd_documents(db, kb_id)

@router.post("/knowledge-bases/{kb_id}/prd-documents/upload", response_model=PrdDocumentResponse, status_code=201)
async def upload_prd(kb_id: str, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "txt"
    if ext not in {"pdf", "docx", "md", "txt"}: raise HTTPException(400, f"不支持: {ext}")
    content = await file.read()
    raw_text = await ParserService.parse(file.filename or "未命名", content)
    doc = await _kb.create_prd_document(db, kb_id, file.filename or "未命名", ext, raw_text)
    await IndexingService.index_prd(doc)
    return doc

@router.delete("/knowledge-bases/{kb_id}/prd-documents/{doc_id}")
async def delete_prd(kb_id: str, doc_id: str, db: AsyncSession = Depends(get_db)):
    doc = await _kb.get_prd_document(db, doc_id)
    if not doc or doc.kb_id != kb_id: raise HTTPException(404, "不存在")
    await _kb.delete_prd_document(db, doc)
    await IndexingService.remove(PRD_COLLECTION, doc_id)
    return {"message": "删除成功"}

# ── 缺陷记录 ──

@router.get("/knowledge-bases/{kb_id}/defect-records", response_model=list[DefectRecordResponse])
async def list_defects(kb_id: str, db: AsyncSession = Depends(get_db)): return await _kb.list_defect_records(db, kb_id)

@router.post("/knowledge-bases/{kb_id}/defect-records", response_model=DefectRecordResponse, status_code=201)
async def create_defect(kb_id: str, data: DefectRecordCreate, db: AsyncSession = Depends(get_db)):
    record = await _kb.create_defect_record(db, kb_id, data.model_dump())
    await IndexingService.index_defect(record)
    return record

@router.put("/knowledge-bases/{kb_id}/defect-records/{record_id}", response_model=DefectRecordResponse)
async def update_defect(kb_id: str, record_id: str, data: DefectRecordUpdate, db: AsyncSession = Depends(get_db)):
    r = await _kb.get_defect_record(db, record_id)
    if not r or r.kb_id != kb_id: raise HTTPException(404, "不存在")
    updated = await _kb.update_defect_record(db, r, data.model_dump(exclude_unset=True))
    await IndexingService.index_defect(updated)
    return updated

@router.delete("/knowledge-bases/{kb_id}/defect-records/{record_id}")
async def delete_defect(kb_id: str, record_id: str, db: AsyncSession = Depends(get_db)):
    r = await _kb.get_defect_record(db, record_id)
    if not r or r.kb_id != kb_id: raise HTTPException(404, "不存在")
    await _kb.delete_defect_record(db, r)
    await IndexingService.remove(DEFECT_COLLECTION, record_id)
    return {"message": "删除成功"}

# ── 导入 ──

@router.post("/knowledge-bases/{kb_id}/import-defects")
async def import_defects(kb_id: str, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    content = await file.read()
    records = ExcelImportService.parse_defect_records(content)
    created = [await _kb.create_defect_record(db, kb_id, r) for r in records]
    for rec in created:
        await IndexingService.index_defect(rec)
    return {"imported": len(created)}

# ── 检索 ──

from pydantic import BaseModel, Field

class RetrieveRequest(BaseModel):
    query: str
    kb_ids: list[str] = Field(default_factory=list)

@router.post("/retrieve")
async def retrieve_knowledge(body: RetrieveRequest, db: AsyncSession = Depends(get_db)):
    from app.services.retrieval_service import RetrievalService
    return await RetrievalService.retrieve(db, body.query, kb_ids=body.kb_ids if body.kb_ids else None)
