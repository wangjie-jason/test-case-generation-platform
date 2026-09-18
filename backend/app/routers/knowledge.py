from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User
from app.models.field_dict import FieldDict
from app.models.business_rule import BusinessRule
from app.models.state_machine import StateMachine
from app.models.term_mapping import TermMapping
from app.models.prd_document import PrdDocument
from app.models.defect_record import DefectRecord
from app.models.test_case import TestCase
from app.routers.deps import get_current_user
from app.services import access_service, llm_credential_service
from app.services.crypto_service import CryptoError
from app.utils import llm_credentials
from app.schemas.knowledge import (
    BusinessRuleCreate,
    BusinessRuleResponse,
    BusinessRuleUpdate,
    DefectRecordCreate,
    DefectRecordResponse,
    DefectRecordUpdate,
    FeishuImportRequest,
    FieldDictCreate,
    FieldDictResponse,
    FieldDictUpdate,
    PrdDocumentResponse,
    StateMachineCreate,
    StateMachineResponse,
    StateMachineUpdate,
    TermMappingCreate,
    TermMappingResponse,
    TermMappingUpdate,
)
from app.schemas.project import KnowledgeBaseCreate, KnowledgeBaseResponse, KnowledgeBaseUpdate
from app.services.knowledge_service import KnowledgeService
from app.services.parser_service import ParserService
from app.services.excel_service import ExcelImportService
from app.services.indexing_service import IndexingService, PRD_COLLECTION, DEFECT_COLLECTION
from app.services.feishu_service import FeishuImportError, import_from_url as feishu_import_from_url

router = APIRouter()
_kb = KnowledgeService()


async def _owner_name_map(db: AsyncSession, kbs: list[KnowledgeBase]) -> dict[str, str]:
    ids = {k.owner_id for k in kbs}
    if not ids:
        return {}
    users = await db.scalars(select(User).where(User.id.in_(ids)))
    return {u.id: (u.display_name or u.username) for u in users}


async def _kb_payload(db: AsyncSession, kb: KnowledgeBase, user: User,
                      name_map: dict[str, str] | None = None) -> dict:
    if name_map is None:
        owner = await db.get(User, kb.owner_id)
        owner_name = (owner.display_name or owner.username) if owner else None
    else:
        owner_name = name_map.get(kb.owner_id)
    return {
        "id": kb.id, "name": kb.name, "description": kb.description,
        "owner_id": kb.owner_id, "visibility": kb.visibility,
        "owner_name": owner_name, "can_manage": access_service.can_manage(kb, user),
        "created_at": kb.created_at, "updated_at": kb.updated_at,
    }


# ── 知识库 ──

@router.post("/knowledge-bases", response_model=KnowledgeBaseResponse, status_code=201)
async def create_kb(data: KnowledgeBaseCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = KnowledgeBase(
        name=data.name, description=data.description,
        visibility=data.visibility, owner_id=user.id,
    )
    db.add(kb)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(400, "同名团队知识库已存在") from exc
    await db.refresh(kb)
    return await _kb_payload(db, kb, user)

@router.get("/knowledge-bases", response_model=list[KnowledgeBaseResponse])
async def list_kbs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kbs = list(await db.scalars(
        select(KnowledgeBase)
        .where((KnowledgeBase.owner_id == user.id) | (KnowledgeBase.visibility == access_service.TEAM))
        .order_by(KnowledgeBase.created_at.desc())
    ))
    name_map = await _owner_name_map(db, kbs)
    return [await _kb_payload(db, k, user, name_map) for k in kbs]

@router.put("/knowledge-bases/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_kb(kb_id: str, data: KnowledgeBaseUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # 团队库只有创建者/管理员能改；个人库只有本人能改（读不到即 404）。
    kb = await access_service.get_kb_or_404(db, kb_id, user, require_manage=True)
    values = data.model_dump(exclude_unset=True)
    if "name" in values and values["name"]:
        kb.name = values["name"].strip()
    if "description" in values:
        kb.description = values["description"]  # 显式 None = 清空
    if "visibility" in values and values["visibility"]:
        kb.visibility = values["visibility"]
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(400, "同名知识库已存在") from exc
    await db.refresh(kb)
    return await _kb_payload(db, kb, user)

@router.delete("/knowledge-bases/{kb_id}")
async def delete_kb(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await access_service.get_kb_or_404(db, kb_id, user, require_manage=True)
    # SQLite 未开 foreign_keys pragma，ON DELETE 不生效，必须显式级联，
    # 否则六张子表与两个向量集合会留下孤儿、test_cases 悬着已删的 kb_id。
    for model in (FieldDict, BusinessRule, StateMachine, TermMapping, PrdDocument, DefectRecord):
        await db.execute(model.__table__.delete().where(model.kb_id == kb_id))
    await db.execute(TestCase.__table__.update().where(TestCase.kb_id == kb_id).values(kb_id=None))
    await db.delete(kb)
    await db.commit()
    # 向量删除放事务外（阻塞调用），失败只记日志、不影响主删除。
    await IndexingService.remove_kb(PRD_COLLECTION, kb_id)
    await IndexingService.remove_kb(DEFECT_COLLECTION, kb_id)
    return {"message": "删除成功"}

# ── 知识项 CRUD（按知识库隔离） ──

def _make_crud(prefix, list_fn, create_fn, get_fn, update_fn, delete_fn, create_schema, update_schema, response_schema):
    sub = APIRouter()
    @sub.get("", response_model=list[response_schema])
    async def list_items(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        # 团队库人人可读、个人库仅本人（读不到即 404）。
        await access_service.get_kb_or_404(db, kb_id, user, require_manage=False)
        return await list_fn(db, kb_id)
    @sub.post("", response_model=response_schema, status_code=201)
    async def create_item(kb_id: str, data: create_schema, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        await access_service.get_kb_or_404(db, kb_id, user, require_manage=True)
        return await create_fn(db, kb_id, data.model_dump())
    @sub.put("/{item_id}", response_model=response_schema)
    async def update_item(kb_id: str, item_id: str, data: update_schema, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        await access_service.get_kb_or_404(db, kb_id, user, require_manage=True)
        item = await get_fn(db, item_id)
        if not item or item.kb_id != kb_id: raise HTTPException(404, "记录不存在")
        return await update_fn(db, item, data.model_dump(exclude_unset=True))
    @sub.delete("/{item_id}")
    async def delete_item(kb_id: str, item_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        await access_service.get_kb_or_404(db, kb_id, user, require_manage=True)
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
async def list_prd_documents(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await access_service.get_kb_or_404(db, kb_id, user)
    return await _kb.list_prd_documents(db, kb_id)

@router.post("/knowledge-bases/{kb_id}/prd-documents/upload", response_model=PrdDocumentResponse, status_code=201)
async def upload_prd(kb_id: str, file: UploadFile = File(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await access_service.get_kb_or_404(db, kb_id, user, require_manage=True)
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "txt"
    if ext not in {"pdf", "docx", "md", "txt"}: raise HTTPException(400, f"不支持: {ext}")
    content = await file.read()
    # 图片 OCR 用当前用户凭据（个人优先、否则系统兜底）；都没配则降级，不挡上传。
    try:
        creds = await llm_credential_service.resolve_credentials_optional(db, user.id)
    except CryptoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        with llm_credentials.bind(creds):
            raw_text = await ParserService.parse(file.filename or "未命名", content)
    except Exception as exc:  # noqa: BLE001 扩展名合法但内容损坏（坏 docx/pdf），转 400 而非 500
        raise HTTPException(status_code=400, detail="文件无法解析，请确认文件未损坏且格式正确") from exc
    doc = await _kb.create_prd_document(db, kb_id, file.filename or "未命名", ext, raw_text)
    await IndexingService.index_prd(doc)
    return doc


@router.post("/knowledge-bases/{kb_id}/prd-documents/from-feishu", response_model=PrdDocumentResponse, status_code=201)
async def import_prd_from_feishu(kb_id: str, req: FeishuImportRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """从飞书文档 / Wiki 节点导入 PRD。按 obj_token 去重，重复导入覆盖原记录并重建向量索引。"""
    await access_service.get_kb_or_404(db, kb_id, user, require_manage=True)
    try:
        result = await feishu_import_from_url(req.url)
    except FeishuImportError as e:
        raise HTTPException(400, str(e))
    if not result.content.strip():
        raise HTTPException(400, "飞书文档内容为空，无法导入")
    # 用飞书返回的 title 作为文件名，加后缀便于列表识别来源。
    filename = f"{result.title}.{result.file_format}"
    doc, _created = await _kb.upsert_feishu_prd_document(
        db, kb_id, filename, result.file_format, result.content, result.obj_token,
        image_tokens=result.image_tokens,
    )
    await IndexingService.index_prd(doc)
    return doc

@router.delete("/knowledge-bases/{kb_id}/prd-documents/{doc_id}")
async def delete_prd(kb_id: str, doc_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await access_service.get_kb_or_404(db, kb_id, user, require_manage=True)
    doc = await _kb.get_prd_document(db, doc_id)
    if not doc or doc.kb_id != kb_id: raise HTTPException(404, "不存在")
    await _kb.delete_prd_document(db, doc)
    await IndexingService.remove(PRD_COLLECTION, doc_id)
    return {"message": "删除成功"}

# ── 缺陷记录 ──

@router.get("/knowledge-bases/{kb_id}/defect-records", response_model=list[DefectRecordResponse])
async def list_defects(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await access_service.get_kb_or_404(db, kb_id, user)
    return await _kb.list_defect_records(db, kb_id)

@router.post("/knowledge-bases/{kb_id}/defect-records", response_model=DefectRecordResponse, status_code=201)
async def create_defect(kb_id: str, data: DefectRecordCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await access_service.get_kb_or_404(db, kb_id, user, require_manage=True)
    record = await _kb.create_defect_record(db, kb_id, data.model_dump())
    await IndexingService.index_defect(record)
    return record

@router.put("/knowledge-bases/{kb_id}/defect-records/{record_id}", response_model=DefectRecordResponse)
async def update_defect(kb_id: str, record_id: str, data: DefectRecordUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await access_service.get_kb_or_404(db, kb_id, user, require_manage=True)
    r = await _kb.get_defect_record(db, record_id)
    if not r or r.kb_id != kb_id: raise HTTPException(404, "不存在")
    updated = await _kb.update_defect_record(db, r, data.model_dump(exclude_unset=True))
    await IndexingService.index_defect(updated)
    return updated

@router.delete("/knowledge-bases/{kb_id}/defect-records/{record_id}")
async def delete_defect(kb_id: str, record_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await access_service.get_kb_or_404(db, kb_id, user, require_manage=True)
    r = await _kb.get_defect_record(db, record_id)
    if not r or r.kb_id != kb_id: raise HTTPException(404, "不存在")
    await _kb.delete_defect_record(db, r)
    await IndexingService.remove(DEFECT_COLLECTION, record_id)
    return {"message": "删除成功"}

# ── 导入 ──

@router.post("/knowledge-bases/{kb_id}/import-defects")
async def import_defects(kb_id: str, file: UploadFile = File(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await access_service.get_kb_or_404(db, kb_id, user, require_manage=True)
    content = await file.read()
    try:
        records = ExcelImportService.parse_defect_records(content)
    except ValueError as exc:
        # 缺必要列等业务校验，保留原始提示。
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 不是有效 Excel（openpyxl 抛 InvalidFileError），转 400
        raise HTTPException(status_code=400, detail="文件无法解析，请确认是有效的 Excel 文件") from exc
    created = [await _kb.create_defect_record(db, kb_id, r) for r in records]
    for rec in created:
        await IndexingService.index_defect(rec)
    return {"imported": len(created)}
