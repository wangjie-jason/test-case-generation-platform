import json
from datetime import datetime, timedelta
from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, now_local
from app.models.review_record import ReviewRecord
from app.models.test_case import TestCase
from app.schemas.generation import (
    CreateCaseRequest,
    ExportCasesRequest,
    GenerateRequest,
    ReviewCaseRequest,
    UpdateCaseRequest,
)
from app.models.user import User
from app.routers.deps import get_current_user
from app.services import access_service, llm_credential_service, usage_service
from app.services.excel_service import ExcelExportService
from app.services.pipeline_service import GeneratorService
from app.services.llm_service import LLMServiceError
from app.services.parser_service import ParserService
from app.services.task_service import TaskManager
from app.utils import llm_credentials
from app.utils.llm_credentials import CredentialNotConfiguredError

router = APIRouter()

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


async def _get_owned_case_or_404(db: AsyncSession, case_id: str, user: User) -> TestCase:
    tc = await db.get(TestCase, case_id)
    # 不属于本人一律 404，不泄露他人用例的存在性。
    if not tc or tc.owner_id != user.id:
        raise HTTPException(404, "用例不存在")
    return tc


def _case_payload(tc: TestCase, review: dict | None) -> dict:
    """用例的统一响应体。列表/编辑/新增三个接口共用，避免字段集漂移——
    早先三处各自手写 dict，create_case 漏了 origin，前端「补充」标签靠巧合才没出错。"""
    return {
        "id": tc.id,
        "title": tc.title,
        "priority": tc.priority,
        "precondition": tc.precondition,
        "expected_result": tc.expected_result,
        "steps": tc.steps,
        "source": tc.source,
        "origin": tc.origin,
        "batch_id": tc.batch_id,
        "req_text": tc.req_text,
        "created_at": str(tc.created_at),
        "edited": bool(tc.edited),
        "edited_at": str(tc.edited_at) if tc.edited_at else None,
        "review": review,
    }


async def _resolve_insert_ts(db: AsyncSession, batch_id: str,
                             prev_id: str | None, next_id: str | None,
                             owner_id: str) -> datetime:
    """算手动插入用例的 created_at——列表按 created_at 升序展示，所以时间戳就是位置。
    - 传了 prev/next：取两者中点
    - 只传 prev（末尾追加）：prev + 1 秒
    - 只传 next（开头插入）：next - 1 秒
    - 都不传：当前时间（等价于末尾追加）
    锚点不属于本批次/本人时忽略，避免跨批次或越权插错位置。
    多次插入同位置时中点会逐渐收敛到同一微秒，SQLite 此时按 rowid 插入顺序返回，
    额外插入的几条天然排在一起，不影响业务。"""
    prev_ts: datetime | None = None
    next_ts: datetime | None = None
    if prev_id:
        prev_case = await db.get(TestCase, prev_id)
        if prev_case and prev_case.batch_id == batch_id and prev_case.owner_id == owner_id:
            prev_ts = prev_case.created_at
    if next_id:
        next_case = await db.get(TestCase, next_id)
        if next_case and next_case.batch_id == batch_id and next_case.owner_id == owner_id:
            next_ts = next_case.created_at

    if prev_ts is not None and next_ts is not None:
        return prev_ts + (next_ts - prev_ts) / 2
    if prev_ts is not None:
        return prev_ts + timedelta(seconds=1)
    if next_ts is not None:
        return next_ts - timedelta(seconds=1)
    return now_local()


@router.post("/generate/clarify")
async def generate_clarify(
    body: GenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """基于知识库补全需求：返回结构化的完整需求说明（Markdown），供用户确认/编辑后再生成用例。"""
    try:
        creds = await llm_credential_service.resolve_credentials(db, user.id)
    except CredentialNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        # clarify 也要记账：它是一次完整的大 prompt 调用，不记的话看板上
        # 「累计」会明显小于账单。无批次归属，流水的 batch_id 留 NULL。
        with llm_credentials.bind(creds), usage_service.collector() as usage_records:
            try:
                kb_ids = await access_service.resolve_kb_ids(db, user, body.kb_ids or None)
                clarified = await GeneratorService.clarify(
                    db, body.requirement_text, kb_ids=kb_ids, owner_id=user.id)
            finally:
                await usage_service.flush(db, usage_records, owner_id=user.id)
    except LLMServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"clarified_text": clarified}


@router.post("/generate/async")
async def generate_async(
    body: GenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """启动后台生成任务，立即返回 task_id。任务脱离本请求运行，
    客户端断开/刷新后仍继续，可凭 task_id 重连观看实时进度。归属登录用户。"""
    # 入口前置校验凭据：没配个人 key 也没有系统兜底时直接 400 引导，不建任务、不花钱。
    try:
        creds = await llm_credential_service.resolve_credentials(db, user.id)
    except CredentialNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 自报的 kb_ids 收敛到可见集合，越界 400。
    kb_ids = await access_service.resolve_kb_ids(db, user, body.kb_ids or None)
    task = TaskManager.create(
        body.requirement_text, body.batch_name, kb_ids,
        owner_id=user.id, creds=creds,
    )
    return task.summary()


@router.get("/generate/active")
async def generate_active(user: User = Depends(get_current_user)):
    """列出当前登录用户运行中的生成任务，供刷新后提供「继续查看」入口。"""
    return [t.summary() for t in TaskManager.active(user.id)]


@router.get("/generate/stream/{task_id}")
async def generate_stream_reconnect(task_id: str, user: User = Depends(get_current_user)):
    """订阅指定任务的事件流：先重放已产生的事件，再推送后续实时事件。
    支持刷新页面后重连，断点续看。只能订阅自己的任务，他人任务一律 404（不泄露存在性）。"""
    task = TaskManager.get(task_id)
    if not task or task.owner_id != user.id:
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


@router.get("/cases/batches")
async def list_batches(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """按 batch_id 汇总当前用户的历史批次：一次返回每批的总数/最新时间/需求文本。
    历史/审核页用这个先渲染批次卡（折叠态），展开某批时再走 /cases?batch_id=xxx
    拉该批的用例明细，避免一次拉全被 limit 截断（旧的 /cases 写死 200 就是这个坑）。"""
    # 用聚合查询代替"拉全部再前端 group by"，即使批次上万也只回几百行。
    stmt = (
        select(
            TestCase.batch_id,
            func.count(TestCase.id).label("total"),
            func.max(TestCase.created_at).label("created_at"),
            func.max(TestCase.req_text).label("req_text"),
        )
        .where(TestCase.owner_id == user.id)
        .group_by(TestCase.batch_id)
        .order_by(func.max(TestCase.created_at).desc())
    )
    rows = (await db.execute(stmt)).all()

    # 每批的审核进度：一次 GROUP BY 出 approved / total_reviewed，避免 N+1。
    review_stmt = (
        select(
            TestCase.batch_id,
            func.count(ReviewRecord.id).label("reviewed"),
            func.sum(case((ReviewRecord.status == "approved", 1), else_=0)).label("approved"),
        )
        .join(ReviewRecord, ReviewRecord.case_id == TestCase.id)
        .where(TestCase.owner_id == user.id)
        .group_by(TestCase.batch_id)
    )
    review_map = {row.batch_id: (row.reviewed or 0, row.approved or 0) for row in (await db.execute(review_stmt)).all()}

    # 每批的 token 消耗：一次 GROUP BY 出全部批次，避免 N+1。
    # 该功能上线前的历史批次没有流水，取不到就是 None——前端对 None 不显示，
    # 不拿 0 冒充「这批没花 token」。
    token_map = await usage_service.batch_tokens(db, user.id)

    result = []
    for row in rows:
        reviewed, approved = review_map.get(row.batch_id, (0, 0))
        result.append({
            "batch_id": row.batch_id or "unknown",
            "total": row.total,
            "reviewed": reviewed,
            "approved": approved,
            "req_text": row.req_text or "",
            "created_at": str(row.created_at) if row.created_at else "",
            "tokens": token_map.get(row.batch_id),
        })
    return result


@router.get("/cases")
async def list_cases(batch_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """列出某批次的全部用例（无上限，一次拉完）。batch_id 必填且必须属于当前用户——
    历史/审核页先调 /cases/batches 拿汇总，再对展开的那一批调本接口拉明细。
    早先允许不传 batch_id 返回最近 5000 条概览，前端已全部改走批次维度，该分支已移除。"""
    # 先确认批次归属：不属于本人时返回 404（不泄露他人批次的存在）。
    owns = await db.scalar(
        select(TestCase.id).where(TestCase.batch_id == batch_id, TestCase.owner_id == user.id).limit(1)
    )
    if not owns:
        raise HTTPException(404, "批次不存在")
    # 批次详情按 case 生成顺序展示（LLM 逐条产出的自然顺序），与"生成结果"页一致。
    # 同一批 case 是在 persist_cases 里几乎同时写入的，用 created_at ASC 就等于生成顺序。
    # 手动插入的 case 通过 created_at = 前后两条中点，自然排到目标位置。
    stmt = select(TestCase).where(
        TestCase.batch_id == batch_id, TestCase.owner_id == user.id
    ).order_by(TestCase.created_at.asc())
    cases = (await db.execute(stmt)).scalars().all()
    case_ids = [c.id for c in cases]
    review_map = {}
    if case_ids:
        rr = await db.execute(select(ReviewRecord).where(ReviewRecord.case_id.in_(case_ids)))
        for rec in rr.scalars().all(): review_map[rec.case_id] = {"status": rec.status, "reject_reason": rec.reject_reason}
    return [_case_payload(c, review_map.get(c.id)) for c in cases]


@router.patch("/cases/{case_id}")
async def update_case(case_id: str, data: UpdateCaseRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """审核阶段的人工微调：允许改 title/priority/precondition/steps/expected_result 五字段。
    编辑只改用例内容 + 打 edited 标记，不碰 review 记录。
    好处：
    - 原始 reject_reason（如 context_missing）保留不丢，AI 训练信号完整
    - 已 reject 的 case 编辑后内容已补全，前端可据此让它出现在导出中
    - 已 approve 的 case 编辑后仍是 approved，只是多一个「已编辑」标记"""
    tc = await _get_owned_case_or_404(db, case_id, user)

    # 只接受这五个字段；未传的字段保持原值，允许只改一处。前端目前是整表提交，
    # 但接口设计成 patch 语义，方便后续做 inline 快改。priority 允许改成 None（清空）。
    # 字段清单取自 schema 本身，避免与 UpdateCaseRequest 手写两份再漂移。
    editable = tuple(UpdateCaseRequest.model_fields)
    touched = False
    values = data.model_dump(exclude_unset=True)
    for k in editable:
        if k in values and values[k] is not None:
            new_val = values[k]
            # steps 允许前端传数组或字符串；DB 里 steps 是 Text，跟 task_service 的写入保持一致——数组转 JSON 存。
            if k == "steps" and isinstance(new_val, list):
                new_val = json.dumps(new_val, ensure_ascii=False)
            if getattr(tc, k) != new_val:
                setattr(tc, k, new_val)
                touched = True

    if touched:
        tc.edited = True
        tc.edited_at = now_local()

    # 编辑不碰 review 记录！保留原始 reject_reason 信号。
    # 前端拿到 edited=True 后，可自行决定导出时包含编辑过的用例。
    rr = await db.execute(select(ReviewRecord).where(ReviewRecord.case_id == case_id))
    rec = rr.scalars().first()
    review_info = {"status": rec.status, "reject_reason": rec.reject_reason} if rec else None

    await db.commit()
    return _case_payload(tc, review_info)


@router.post("/cases")
async def create_case(data: CreateCaseRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """审核时手动插入用例。前端传 batch_id + 内容字段 + 可选 prev_case_id/next_case_id 锚点。
    定位策略见 _resolve_insert_ts：新 case 的 created_at 落在前后两条之间，自然排到目标位置。
    手动插入的 case source='manual'、edited=True、review 直接置 approved。"""
    batch_id = data.batch_id
    title = data.title.strip()
    if not title:
        raise HTTPException(400, "title 必填")

    # 批次必须属于本人，否则 404（不能往他人批次插用例）。
    batch_ref = (await db.execute(
        select(TestCase).where(TestCase.batch_id == batch_id, TestCase.owner_id == user.id).limit(1)
    )).scalar_one_or_none()
    if not batch_ref:
        raise HTTPException(404, "批次不存在")

    new_ts = await _resolve_insert_ts(db, batch_id, data.prev_case_id, data.next_case_id, user.id)

    steps = data.steps or ""
    if isinstance(steps, list):
        steps = json.dumps(steps, ensure_ascii=False)

    new_case = TestCase(
        title=title,
        priority=(data.priority or None),
        precondition=data.precondition,
        steps=steps,
        expected_result=data.expected_result,
        source="manual",
        edited=True,
        edited_at=now_local(),
        created_at=new_ts,
        batch_id=batch_id,
        owner_id=user.id,
        req_text=batch_ref.req_text if batch_ref else None,
        kb_id=batch_ref.kb_id if batch_ref else None,
    )
    db.add(new_case)
    # UUID 主键在 flush 前是 None，必须先 flush 让 new_case.id 落地，再挂 ReviewRecord.case_id
    await db.flush()
    # 手动插入的用例默认已审可用：内容是用户自己写的，直接 approve 免得再点一次
    db.add(ReviewRecord(case_id=new_case.id, status="approved"))
    await db.commit()
    await db.refresh(new_case)

    return _case_payload(new_case, {"status": "approved", "reject_reason": None})


@router.post("/cases/{case_id}/review")
async def review_case(case_id: str, data: ReviewCaseRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tc = await _get_owned_case_or_404(db, case_id, user)
    status = data.status
    rr = await db.execute(select(ReviewRecord).where(ReviewRecord.case_id == case_id))
    rec = rr.scalars().first()
    if rec: rec.status = status; rec.reject_reason = data.reject_reason if status == "rejected" else None
    else:
        rec = ReviewRecord(case_id=case_id, status=status, reject_reason=data.reject_reason if status == "rejected" else None)
        db.add(rec)
    await db.commit()
    return {"status": status}


@router.post("/cases/export")
async def export_cases(data: ExportCasesRequest):
    excel_bytes = ExcelExportService.export_test_cases([case.model_dump() for case in data.cases])
    return StreamingResponse(BytesIO(excel_bytes.getvalue()), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=test_cases.xlsx"})


@router.post("/parse-prd")
async def parse_prd(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "txt"
    if ext not in {"pdf", "docx", "md", "txt"}: raise HTTPException(400, f"不支持: {ext}")
    content = await file.read()
    # 图片 OCR 走多模态模型：绑定当前用户凭据（个人优先、否则系统兜底）；都没配时
    # 不挡上传，图片识别降级为提示文案。
    creds = await llm_credential_service.resolve_credentials_optional(db, user.id)
    with llm_credentials.bind(creds):
        text = await ParserService.parse(file.filename or "未命名", content)
    return {"filename": file.filename, "format": ext, "text": text, "length": len(text)}


@router.get("/stats/overview")
async def stats_overview(scope: str = "me", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """统计概览。scope=me（默认）只含本人；scope=team 全员汇总（所有人可见，
    但只给聚合计数与按模型/按人拆分，不含他人批次明细）。"""
    is_team = scope == "team"
    owner_id = None if is_team else user.id

    case_stmt = select(TestCase)
    if owner_id is not None:
        case_stmt = case_stmt.where(TestCase.owner_id == owner_id)
    total = (await db.execute(case_stmt)).scalars().all()
    total_n = len(total)
    # 批次数按 batch_id 去重，不能复用 total_n——那是用例条数，两者语义不同。
    batch_n = len({c.batch_id for c in total if c.batch_id})

    # 审核记录本身没有 owner，join 用例按人过滤。
    review_stmt = select(ReviewRecord).join(TestCase, ReviewRecord.case_id == TestCase.id)
    if owner_id is not None:
        review_stmt = review_stmt.where(TestCase.owner_id == owner_id)
    reviews = (await db.execute(review_stmt)).scalars().all()
    approved_n = sum(1 for r in reviews if r.status == "approved")
    rejected = [r for r in reviews if r.status == "rejected"]
    reviewed = len(reviews)
    dist: dict[str, int] = {}
    for r in rejected:
        # reject_reason 有一个特殊值 'edited'：AI 一次没到位、人工微调后可用，
        # 归到「不通过」但和幻觉/丢弃并列展示。
        if r.reject_reason: dist[r.reject_reason] = dist.get(r.reject_reason, 0) + 1

    token_usage = (
        await usage_service.team_usage(db) if is_team
        else await usage_service.summary(db, owner_id=user.id)
    )
    return {
        "scope": "team" if is_team else "me",
        "total_cases": total_n,
        "reviewed_cases": reviewed,
        "approved_cases": approved_n,
        "rejected_cases": len(rejected),
        "usability_rate": round((approved_n / reviewed * 100) if reviewed > 0 else 0),
        "hallucination_distribution": dist,
        "generation_count": batch_n,
        "token_usage": token_usage,
    }
