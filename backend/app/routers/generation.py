import asyncio
import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.test_case import TestCase
from app.schemas.generation import GenerateRequest
from app.services.parser_service import ParserService
from app.services.task_service import TaskManager

router = APIRouter()

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.post("/generate/async")
async def generate_async(body: GenerateRequest):
    """启动后台生成任务，立即返回 task_id。任务脱离本请求运行，
    客户端断开/刷新后仍继续，可凭 task_id 重连观看实时进度。
    body.client_id 作为归属者，实现多人/多浏览器隔离。"""
    task = TaskManager.create(
        body.requirement_text, body.batch_name, body.kb_ids if body.kb_ids else None,
        owner_id=body.client_id,
    )
    return task.summary()


@router.get("/generate/active")
async def generate_active(client_id: str | None = None):
    """列出运行中的生成任务，供前端在刷新后提供「继续查看」入口。
    传入 client_id 时只返回该浏览器/用户自己的任务，避免串到他人任务。"""
    return [t.summary() for t in TaskManager.active(owner_id=client_id)]


@router.get("/generate/stream/{task_id}")
async def generate_stream_reconnect(task_id: str):
    """订阅指定任务的事件流：先重放已产生的事件，再推送后续实时事件。
    支持刷新页面后重连，断点续看。"""
    task = TaskManager.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在或已过期")

    async def stream():
        queue = task.subscribe()
        try:
            while True:
                event = await queue.get()
                if event.get("type") == "__end__":
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            task.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


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
