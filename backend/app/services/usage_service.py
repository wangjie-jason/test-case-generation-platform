"""LLM token 用量的**落库与聚合**（依赖 sqlalchemy）。

采集逻辑（contextvars 收集器、usage 解析、时间边界）在 `app/utils/token_usage.py`，
本模块 re-export 其公开 API，故调用方统一 `from app.services import usage_service`
即可，不必关心两边的分工。

拆分原因：CI 只装 pytest、不装 requirements.txt（避开 chromadb 与 torch），
测试若 import 到 sqlalchemy 就会 ModuleNotFoundError。采集是纯 Python 逻辑，
抽出去即可轻量测试——与 v0.23 把 case_grouping 从 generator_service 抽出同一思路。

落库时机：全程只在内存里 append，等生成任务结束、拿到 batch_id 后一次性 flush。
这样每条流水都带得上批次归属（批次级消耗要靠它），也避免 15 路并发各自开
session 写 SQLite。
"""

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models.llm_usage import LlmUsage

# 采集 API 从纯逻辑模块 re-export：调用方无需知道拆分，统一走 usage_service。
from app.utils.token_usage import (  # noqa: F401
    STAGE_CLARIFY,
    STAGE_GENERATE,
    STAGE_LABELS,
    STAGE_MODULE_SPLIT,
    STAGE_REVIEW,
    STAGE_SUPPLEMENT,
    collector,
    day_start,
    record,
    stage,
    week_start,
)

logger = logging.getLogger(__name__)


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


async def summary(db: AsyncSession) -> dict:
    """看板用的用量汇总：今日 / 本周 / 累计 + 按阶段拆分。"""
    now = now_local()
    today_from = day_start(now)
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
