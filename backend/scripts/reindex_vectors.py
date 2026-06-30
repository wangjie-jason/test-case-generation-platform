"""把 SQLite 里已有的 PRD / 缺陷 / 历史用例全量补写进向量库。

用法（在 backend 目录下，使用装好依赖的解释器）：
    python -m scripts.reindex_vectors

向量库是「补充检索」用的，主存储仍是 SQLite；本脚本可重复执行，
upsert 以 source_id 为键覆盖，不会产生重复。
"""
import asyncio
import logging

from sqlalchemy import select

from app.database import async_session
from app.models import DefectRecord, PrdDocument
from app.models.test_case import TestCase
from app.services.indexing_service import IndexingService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reindex")


async def main() -> None:
    async with async_session() as db:
        prds = (await db.execute(select(PrdDocument))).scalars().all()
        defects = (await db.execute(select(DefectRecord))).scalars().all()
        cases = (await db.execute(select(TestCase))).scalars().all()

        logger.info("开始重建：PRD=%d 缺陷=%d 用例=%d", len(prds), len(defects), len(cases))

        for d in prds:
            await IndexingService.index_prd(d)
        for r in defects:
            await IndexingService.index_defect(r)
        for c in cases:
            await IndexingService.index_case(c)

        logger.info("重建完成")


if __name__ == "__main__":
    asyncio.run(main())
