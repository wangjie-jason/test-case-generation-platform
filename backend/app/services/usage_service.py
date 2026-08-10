"""LLM token 用量采集与聚合。

采集为什么走 contextvars 而不是改调用签名：`LLMService()` 在 5 个地方各自 new
（clarify / 模块拆分 / 生成 / 评审 / 补充），其中三处还跑在 `asyncio.create_task`
起的并发 worker 里。要把「这次消耗归属于哪个阶段、哪次任务」层层透传，就得改遍
generator_service 里所有 worker 的签名和 `_parallel_agents` 的协议——收益全无。
contextvars 天然满足这里的需求：`create_task` 会复制创建时的上下文，因此
① 在 task_service 顶层装一次收集器，所有并发 worker 都能写进同一个 sink；
② 每个 worker 内部 `stage()` 只影响自己的上下文副本，并发下不会互相串台。

落库时机：全程只在内存里 append，等生成任务结束、拿到 batch_id 后一次性 flush。
这样每条流水都带得上批次归属（批次级消耗要靠它），也避免 15 路并发各自开
session 写 SQLite。
"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Iterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models.llm_usage import LlmUsage

logger = logging.getLogger(__name__)

# 阶段标识。与生成流程里 progress 事件的 stage 命名保持一致，便于前端复用文案。
STAGE_CLARIFY = "clarify"
STAGE_MODULE_SPLIT = "module_split"
STAGE_GENERATE = "generate"
STAGE_REVIEW = "review"
STAGE_SUPPLEMENT = "supplement"

STAGE_LABELS = {
    STAGE_CLARIFY: "需求补全",
    STAGE_MODULE_SPLIT: "模块拆分",
    STAGE_GENERATE: "用例生成",
    STAGE_REVIEW: "评审",
    STAGE_SUPPLEMENT: "补充",
    "unknown": "未标注",
}

_sink: ContextVar[list[dict] | None] = ContextVar("llm_usage_sink", default=None)
_stage: ContextVar[str] = ContextVar("llm_usage_stage", default="unknown")


@contextmanager
def collector() -> Iterator[list[dict]]:
    """在当前上下文装一个用量收集器，yield 出的列表会收到本次调用链的所有流水。

    必须在起并发 worker **之前**装好：`create_task` 复制的是创建那一刻的上下文，
    装晚了 worker 就看不到这个 sink，用量会静默丢失。
    """
    records: list[dict] = []
    token = _sink.set(records)
    try:
        yield records
    finally:
        _sink.reset(token)


@contextmanager
def stage(name: str) -> Iterator[None]:
    """标注接下来的 LLM 调用属于哪个阶段。用 reset 而非直接 set，避免退出后污染外层。"""
    token = _stage.set(name)
    try:
        yield
    finally:
        _stage.reset(token)


def record(model: str, usage: dict) -> None:
    """把服务端上报的一段 usage 记进当前 sink。没装收集器时静默跳过。

    静默跳过是有意的：llm_service 是通用封装，脚本或测试里直接调它不该因为
    没有采集上下文就报错。代价是漏采，但漏采只影响统计，不影响生成本身。
    """
    sink = _sink.get()
    if sink is None:
        return
    if not isinstance(usage, dict):
        return

    prompt = _as_int(usage.get("prompt_tokens"))
    completion = _as_int(usage.get("completion_tokens"))
    total = _as_int(usage.get("total_tokens")) or (prompt + completion)
    # 推理 token 在 OpenAI / DeepSeek 兼容协议里放在 completion_tokens_details 下。
    # 它已被计入 completion_tokens，这里单独取出只为回答「思考占多少」。
    details = usage.get("completion_tokens_details")
    reasoning = _as_int(details.get("reasoning_tokens")) if isinstance(details, dict) else 0

    # 三个计数全为 0 说明服务端没真正上报（或上报了空壳），记下来只会污染统计。
    if not (prompt or completion or total):
        return

    sink.append({
        "stage": _stage.get(),
        "model": model,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "total_tokens": total,
    })


def _as_int(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


async def flush(db: AsyncSession, records: list[dict], batch_id: str | None = None) -> None:
    """把收集到的流水写库。batch_id 非空时回填到每条上，供批次级消耗展示。

    统计功能失败绝不能连坐生成结果：这里整体 try 住，出错只打日志。用例已经
    落库成功了，不该因为记账写不进去就把任务标成失败。
    """
    if not records:
        return
    try:
        for r in records:
            db.add(LlmUsage(
                stage=r.get("stage") or "unknown",
                model=r.get("model") or "",
                prompt_tokens=r.get("prompt_tokens", 0),
                completion_tokens=r.get("completion_tokens", 0),
                reasoning_tokens=r.get("reasoning_tokens", 0),
                total_tokens=r.get("total_tokens", 0),
                batch_id=batch_id,
            ))
        await db.commit()
    except Exception:
        logger.exception("token 用量写库失败（不影响生成结果），丢弃 %d 条流水", len(records))
        await db.rollback()


def _day_start(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def week_start(dt: datetime) -> datetime:
    """本周起始（周一 00:00）。库里存的是 naive 的 Asia/Shanghai 时间，直接比较即可。"""
    return _day_start(dt) - timedelta(days=dt.weekday())


async def summary(db: AsyncSession) -> dict:
    """看板用的用量汇总：今日 / 本周 / 累计 + 按阶段拆分。"""
    now = now_local()
    today_from = _day_start(now)
    week_from = week_start(now)

    async def _sum_since(since: datetime | None) -> int:
        stmt = select(func.coalesce(func.sum(LlmUsage.total_tokens), 0))
        if since is not None:
            stmt = stmt.where(LlmUsage.created_at >= since)
        return int((await db.execute(stmt)).scalar() or 0)

    today = await _sum_since(today_from)
    week = await _sum_since(week_from)
    total = await _sum_since(None)

    # 按阶段拆分：用累计而非本周，样本更足、占比更稳（本周初可能只有一两次生成）。
    stage_rows = (await db.execute(
        select(
            LlmUsage.stage,
            func.coalesce(func.sum(LlmUsage.total_tokens), 0).label("tokens"),
            func.count(LlmUsage.id).label("calls"),
        ).group_by(LlmUsage.stage).order_by(func.sum(LlmUsage.total_tokens).desc())
    )).all()
    by_stage = [
        {
            "stage": row.stage,
            "label": STAGE_LABELS.get(row.stage, row.stage),
            "tokens": int(row.tokens or 0),
            "calls": int(row.calls or 0),
        }
        for row in stage_rows
    ]

    reasoning_total = int((await db.execute(
        select(func.coalesce(func.sum(LlmUsage.reasoning_tokens), 0))
    )).scalar() or 0)
    calls_total = int((await db.execute(select(func.count(LlmUsage.id)))).scalar() or 0)
    # 已采集流水的起始时间。为 None 说明该功能刚上线、还没采到数据，前端据此提示
    # 「统计自 X 起」，免得把「累计 0」误读成「一次都没生成过」。
    since = (await db.execute(select(func.min(LlmUsage.created_at)))).scalar()

    return {
        "today_tokens": today,
        "week_tokens": week,
        "total_tokens": total,
        "reasoning_tokens": reasoning_total,
        "calls": calls_total,
        "by_stage": by_stage,
        "since": str(since) if since else None,
    }


async def batch_tokens(db: AsyncSession) -> dict[str, int]:
    """各批次的 token 消耗，供批次卡展示。返回 {batch_id: total_tokens}。"""
    rows = (await db.execute(
        select(LlmUsage.batch_id, func.coalesce(func.sum(LlmUsage.total_tokens), 0).label("tokens"))
        .where(LlmUsage.batch_id.is_not(None))
        .group_by(LlmUsage.batch_id)
    )).all()
    return {row.batch_id: int(row.tokens or 0) for row in rows}
