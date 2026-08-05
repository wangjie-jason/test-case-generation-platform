"""重排指定批次（batch_id）用例的展示顺序，让同一子功能的用例挨在一起。

用法（在 backend 目录下，使用装好依赖的解释器）：
    python -m scripts.resort_batch <batch_id> [--dry-run]

列表接口按 created_at 升序返回（routers/generation.py），所以"排序"就是按目标顺序
重写 created_at（起始时间沿用该批次原最早时间，逐条 +1 秒）。

排序规则见 app/utils/case_ordering（三层：顶层块序不变 → 块内路径层级 → 路径段内
功能点单向前移），与生成流程共用同一套实现。生成阶段已在 complete 前自动排好，本脚本
用于补排加该逻辑之前落库的历史批次，以及生成时出问题需要重排的情况。
"""
import asyncio
import logging
import sys
from datetime import timedelta

from sqlalchemy import select

from app.database import async_session
from app.models.test_case import TestCase
from app.utils.case_ordering import order_cases

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("resort_batch")


async def main(batch_id: str, dry_run: bool) -> None:
    async with async_session() as db:
        cases = (
            await db.execute(
                select(TestCase)
                .where(TestCase.batch_id == batch_id)
                .order_by(TestCase.created_at.asc(), TestCase.id.asc())
            )
        ).scalars().all()
        if not cases:
            logger.warning("未找到批次 %s 的任何用例", batch_id)
            return

        ordered = order_cases(list(cases), lambda c: c.title)
        assert len(ordered) == len(cases) and {c.id for c in ordered} == {c.id for c in cases}

        moved = sum(1 for a, b in zip(cases, ordered) if a.id != b.id)
        logger.info("批次 %s：%d 条用例，%d 条位置变化", batch_id, len(cases), moved)
        if dry_run:
            # 标出每条的原位置，便于核对「哪些被移动、移到了哪」——全量平铺打印上千行
            # 却看不出变化，等于没法验收。★ 标记位置有变化的条目。
            orig_pos = {c.id: i for i, c in enumerate(cases)}
            for i, c in enumerate(ordered):
                was = orig_pos[c.id]
                mark = f"  ← 原 {was}" if was != i else ""
                logger.info("%s%4d  %s%s", "★" if was != i else " ", i, c.title, mark)
            logger.info("dry-run，未写库：%d 条位置变化", moved)
            return
        if not moved:
            logger.info("顺序已正确，无需写库")
            return

        base = cases[0].created_at
        for i, c in enumerate(ordered):
            c.created_at = base + timedelta(seconds=i)
        await db.commit()
        logger.info("写库完成：created_at 自 %s 起逐条 +1 秒", base)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    if len(args) != 1:
        print("用法: python -m scripts.resort_batch <batch_id> [--dry-run]")
        sys.exit(1)
    asyncio.run(main(args[0], "--dry-run" in sys.argv[1:]))
