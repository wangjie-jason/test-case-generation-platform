"""删除指定批次（batch_id）的全部用例及其历史用例向量。

用法（在 backend 目录下，使用装好依赖的解释器）：
    python -m scripts.delete_batch <batch_id>

先按 case.id 逐条从向量库（historical_cases 集合）删除，再删 SQLite 行。
review_records 通过外键 ON DELETE CASCADE 连带清理。可重复执行。
"""
import asyncio
import logging
import sys

from sqlalchemy import delete, select

from app.database import async_session
from app.models.test_case import TestCase
from app.services.indexing_service import CASE_COLLECTION, IndexingService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("delete_batch")


async def main(batch_id: str) -> None:
    async with async_session() as db:
        cases = (
            await db.execute(select(TestCase).where(TestCase.batch_id == batch_id))
        ).scalars().all()
        if not cases:
            logger.warning("未找到批次 %s 的任何用例，无需删除", batch_id)
            return

        logger.info("批次 %s：待删除用例 %d 条", batch_id, len(cases))

        # 先删向量：以 case.id 为 source_id 定位该用例产生的所有分块
        for c in cases:
            await IndexingService.remove(CASE_COLLECTION, c.id)
        logger.info("向量删除完成（集合 %s）", CASE_COLLECTION)

        # 再删 SQLite 行（review_records 走 CASCADE）
        result = await db.execute(
            delete(TestCase).where(TestCase.batch_id == batch_id)
        )
        await db.commit()
        logger.info("SQLite 删除完成，共 %d 行", result.rowcount)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python -m scripts.delete_batch <batch_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
