import asyncio
import logging

from app.vectorstore.chroma_client import ChromaStore

logger = logging.getLogger(__name__)

# 各集合名与检索侧（retrieval_service / generator_service）保持一致。
PRD_COLLECTION = "prd_documents"
DEFECT_COLLECTION = "defect_records"
CASE_COLLECTION = "historical_cases"


class IndexingService:
    """把知识写入向量库。encode 是阻塞 CPU 操作，统一放线程池执行，
    且任何失败都不应阻断主流程（SQLite 写入才是主存储），仅记日志。"""

    @staticmethod
    async def index_prd(doc) -> None:
        await _safe_upsert(PRD_COLLECTION, doc.raw_text or "", doc.id, doc.kb_id)

    @staticmethod
    async def index_defect(record) -> None:
        text = "\n".join(p for p in [record.title, record.description] if p)
        await _safe_upsert(DEFECT_COLLECTION, text, record.id, record.kb_id)

    @staticmethod
    async def index_case(case) -> None:
        text = "\n".join(p for p in [case.title, case.precondition, case.steps, case.expected_result] if p)
        await _safe_upsert(CASE_COLLECTION, text, case.id, case.kb_id)

    @staticmethod
    async def remove(collection: str, source_id: str) -> None:
        try:
            await asyncio.to_thread(ChromaStore().delete_by_source, collection, source_id)
        except Exception:
            logger.exception("向量删除失败 collection=%s id=%s", collection, source_id)


async def _safe_upsert(collection: str, text: str, source_id: str, kb_id: str | None) -> None:
    if not text.strip():
        return
    meta = {"kb_id": kb_id} if kb_id else {}
    try:
        await asyncio.to_thread(ChromaStore().upsert_texts, collection, [text], [meta], [source_id])
    except Exception:
        logger.exception("向量写入失败 collection=%s id=%s", collection, source_id)
