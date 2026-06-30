import json
import uuid as _uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.test_case import TestCase
from app.schemas.generation import GenerateRequest, GenerateResponse
from app.services.generator_service import GeneratorService
from app.services.indexing_service import IndexingService
from app.services.llm_service import LLMServiceError
from app.services.parser_service import ParserService

router = APIRouter()


async def _persist_cases(db: AsyncSession, cases: list[dict], batch_name: str | None, requirement_text: str) -> str:
    """将生成的用例写入数据库，返回 batch_id。"""
    batch_id = str(_uuid.uuid4())
    created = []
    for c in cases:
        steps = c.get("steps", "")
        if isinstance(steps, list): steps = json.dumps(steps, ensure_ascii=False)
        tc = TestCase(
            title=c.get("title", ""), precondition=c.get("precondition", ""),
            steps=steps, expected_result=c.get("expected_result", ""),
            source="ai", batch_id=batch_id, req_text=batch_name or requirement_text[:80],
            knowledge_refs=json.dumps(c.get("knowledge_refs", []), ensure_ascii=False),
        )
        db.add(tc)
        created.append(tc)
    await db.commit()
    # 生成的用例回灌历史用例向量库，作为后续生成的 few-shot 语料。
    for tc in created:
        await IndexingService.index_case(tc)
    return batch_id


@router.post("/generate", response_model=GenerateResponse)
async def generate_test_cases(body: GenerateRequest, db: AsyncSession = Depends(get_db)):
    try:
        result = await GeneratorService.generate(db, body.requirement_text, kb_ids=body.kb_ids if body.kb_ids else None)
    except LLMServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    await _persist_cases(db, result["cases"], body.batch_name, body.requirement_text)
    return result


@router.post("/generate/stream")
async def generate_stream(body: GenerateRequest, db: AsyncSession = Depends(get_db)):
    async def stream():
        try:
            async for event in GeneratorService.generate_stream(db, body.requirement_text, kb_ids=body.kb_ids if body.kb_ids else None):
                if event.get("type") == "complete":
                    await _persist_cases(db, event.get("cases", []), body.batch_name, body.requirement_text)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except LLMServiceError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/cases")
async def list_cases(db: AsyncSession = Depends(get_db)):
    from app.models.review_record import ReviewRecord
    r = await db.execute(select(TestCase).order_by(TestCase.created_at.desc()).limit(200))
    cases = r.scalars().all()
    case_ids = [c.id for c in cases]
    review_map = {}
    if case_ids:
        rr = await db.execute(select(ReviewRecord).where(ReviewRecord.case_id.in_(case_ids)))
        for rec in rr.scalars().all(): review_map[rec.case_id] = {"status": rec.status, "reject_reason": rec.reject_reason}
    return [{"id": c.id, "title": c.title, "precondition": c.precondition, "expected_result": c.expected_result, "steps": c.steps, "source": c.source, "batch_id": c.batch_id, "req_text": c.req_text, "created_at": str(c.created_at), "review": review_map.get(c.id)} for c in cases]


@router.post("/cases/{case_id}/review")
async def review_case(case_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    from app.models.review_record import ReviewRecord
    tc = await db.get(TestCase, case_id)
    if not tc: raise HTTPException(404, "用例不存在")
    status = data.get("status")
    rr = await db.execute(select(ReviewRecord).where(ReviewRecord.case_id == case_id))
    rec = rr.scalars().first()
    if rec: rec.status = status; rec.reject_reason = data.get("reject_reason") if status == "rejected" else None
    else:
        rec = ReviewRecord(case_id=case_id, status=status, reject_reason=data.get("reject_reason") if status == "rejected" else None)
        db.add(rec)
    await db.commit()
    return {"status": status}


@router.post("/cases/export")
async def export_cases(data: dict):
    from io import BytesIO
    from app.services.excel_service import ExcelExportService
    excel_bytes = ExcelExportService.export_test_cases(data.get("cases", []))
    return StreamingResponse(BytesIO(excel_bytes.getvalue()), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=test_cases.xlsx"})


@router.post("/parse-prd")
async def parse_prd(file: UploadFile = File(...)):
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "txt"
    if ext not in {"pdf", "docx", "md", "txt"}: raise HTTPException(400, f"不支持: {ext}")
    content = await file.read()
    text = await ParserService.parse(file.filename or "未命名", content)
    return {"filename": file.filename, "format": ext, "text": text, "length": len(text)}


@router.get("/stats/overview")
async def stats_overview(db: AsyncSession = Depends(get_db)):
    from app.models.review_record import ReviewRecord
    total = (await db.execute(select(TestCase))).scalars().all()
    total_n = len(total)
    approved = (await db.execute(select(ReviewRecord).where(ReviewRecord.status == "approved"))).scalars().all()
    rejected = (await db.execute(select(ReviewRecord).where(ReviewRecord.status == "rejected"))).scalars().all()
    reviewed = len(approved) + len(rejected)
    dist = {}
    for r in rejected:
        if r.reject_reason: dist[r.reject_reason] = dist.get(r.reject_reason, 0) + 1
    return {"total_cases": total_n, "reviewed_cases": reviewed, "approved_cases": len(approved), "rejected_cases": len(rejected), "usability_rate": round((len(approved) / reviewed * 100) if reviewed > 0 else 0), "hallucination_distribution": dist, "generation_count": total_n}
