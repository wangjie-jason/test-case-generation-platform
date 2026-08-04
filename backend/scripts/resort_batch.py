"""重排指定批次（batch_id）用例的展示顺序，让同一子功能的用例挨在一起。

用法（在 backend 目录下，使用装好依赖的解释器）：
    python -m scripts.resort_batch <batch_id> [--dry-run]

列表接口按 created_at 升序返回（routers/generation.py），所以"排序"就是按目标顺序
重写 created_at（起始时间沿用该批次原最早时间，逐条 +1 秒）。

排序规则分两层，与生成阶段的语义保持一致：
1. 先按顶层模块把用例切成连续块，块的先后不变——顶层顺序来自需求切割的 modules
   列表，那是人给定的阅读顺序，不能按字母或标题重排。
2. 块内按模块层级路径（标题【】里以 - 分隔的各级）做层级化稳定排序，每级的次序取
   该级路径在块内的首次出现位置。于是补充用例会归到自己所属子功能的那一段里，而
   不是堆在模块块尾部；同一子功能内部仍保持原有相对顺序。
"""
import asyncio
import logging
import re
import sys
from datetime import timedelta

from sqlalchemy import select

from app.database import async_session
from app.models.test_case import TestCase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("resort_batch")


def _title_segs(title: str) -> tuple[str, ...]:
    """标题【模块-子模块-...】→ 层级路径元组；没有【】的返回空元组（排到块内原位）。"""
    m = re.match(r"^【(.+?)】", title or "")
    return tuple(s.strip() for s in m.group(1).split("-")) if m else ()


def _split_top_blocks(cases: list[TestCase]) -> list[list[TestCase]]:
    """按顶层模块切成连续块，保持块与块之间的原有先后。"""
    blocks: list[list[TestCase]] = []
    prev = object()
    for c in cases:
        top = _title_segs(c.title)[:1]
        if top != prev:
            blocks.append([c])
            prev = top
        else:
            blocks[-1].append(c)
    return blocks


def _resort_block(block: list[TestCase]) -> list[TestCase]:
    """块内层级化稳定排序：各级路径按其在块内的首次出现位置排。"""
    rank: dict[tuple[str, ...], int] = {}
    for i, c in enumerate(block):
        segs = _title_segs(c.title)
        for depth in range(1, len(segs) + 1):
            rank.setdefault(segs[:depth], i)

    def sort_key(item: tuple[int, TestCase]):
        i, c = item
        segs = _title_segs(c.title)
        # 逐级 rank + 原下标兜底：同一子功能内保持原相对顺序（稳定）
        return tuple(rank[segs[:depth]] for depth in range(1, len(segs) + 1)) + (i,)

    return [c for _, c in sorted(enumerate(block), key=sort_key)]


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

        blocks = _split_top_blocks(cases)
        ordered = [c for b in blocks for c in _resort_block(b)]
        assert len(ordered) == len(cases) and {c.id for c in ordered} == {c.id for c in cases}

        moved = sum(1 for a, b in zip(cases, ordered) if a.id != b.id)
        logger.info(
            "批次 %s：%d 条用例，%d 个顶层模块块，%d 条位置变化",
            batch_id, len(cases), len(blocks), moved,
        )
        if dry_run:
            for i, c in enumerate(ordered):
                logger.info("%4d  %s", i, c.title)
            logger.info("dry-run，未写库")
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
