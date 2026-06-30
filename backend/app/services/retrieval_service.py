import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import BusinessRule, DefectRecord, FieldDict, PrdDocument, StateMachine, TermMapping
from app.utils.text_utils import extract_keywords, strip_urls
from app.vectorstore.chroma_client import ChromaStore

logger = logging.getLogger(__name__)

# 长正文字段（PRD 全文、缺陷描述）单个关键词极易误命中，
# 要求命中的不同关键词数达到该阈值才算真正相关。
LONG_TEXT_MIN_HITS = 2


class RetrievalService:

    @staticmethod
    async def retrieve(db: AsyncSession, query: str, kb_ids: list[str] | None = None, top_k: int = 10, include_vectors: bool = True) -> dict:
        keywords = extract_keywords(query)
        if not keywords:
            return {
                "field_dicts": [],
                "business_rules": [],
                "state_machines": [],
                "term_mappings": [],
                "prd_chunks": [],
                "defect_chunks": [],
                "query_keywords": [],
            }

        field_dicts = await _search(FieldDict, db, keywords, kb_ids, [FieldDict.field_name, FieldDict.display_name, FieldDict.description])
        business_rules = await _search(BusinessRule, db, keywords, kb_ids, [BusinessRule.rule_name, BusinessRule.expression, BusinessRule.description])
        state_machines = await _search(StateMachine, db, keywords, kb_ids, [StateMachine.entity, StateMachine.from_state, StateMachine.to_state])
        term_mappings = await _search(TermMapping, db, keywords, kb_ids, [TermMapping.ui_term, TermMapping.tech_field, TermMapping.mapping_desc])
        # PRD 全文和缺陷描述属于长正文，单关键词易误命中，需按命中数过滤。
        prd_docs = await _search_long_text(PrdDocument, db, keywords, kb_ids, "raw_text", extra_fields=[PrdDocument.filename])
        defects = await _search_long_text(DefectRecord, db, keywords, kb_ids, "description", extra_fields=[DefectRecord.title])

        prd_chunks = _vector_chunks("prd_documents", query, top_k, prd_docs, "raw_text", include_vectors, kb_ids)
        defect_chunks = _vector_chunks("defect_records", query, top_k, defects, "description", include_vectors, kb_ids)

        return {
            "field_dicts": [_fd(f) for f in field_dicts],
            "business_rules": [{"id": r.id, "rule_name": r.rule_name, "rule_type": r.rule_type, "expression": r.expression, "description": r.description} for r in business_rules],
            "state_machines": [{"id": s.id, "entity": s.entity, "from_state": s.from_state, "to_state": s.to_state, "condition": s.condition} for s in state_machines],
            "term_mappings": [{"id": t.id, "ui_term": t.ui_term, "tech_field": t.tech_field, "mapping_desc": t.mapping_desc} for t in term_mappings],
            "prd_chunks": prd_chunks,
            "defect_chunks": defect_chunks,
            "query_keywords": keywords,
        }


async def _search(model, db, keywords, kb_ids, fields):
    if not keywords:
        return []
    conditions = []
    for kw in keywords:
        for f in fields:
            conditions.append(f.contains(kw))
    stmt = select(model)
    if conditions: stmt = stmt.where(or_(*conditions))
    if kb_ids:
        if hasattr(model, 'kb_id'): stmt = stmt.where(model.kb_id.in_(kb_ids))
    r = await db.execute(stmt.limit(10))
    return list(r.scalars().all())


async def _search_long_text(model, db, keywords, kb_ids, text_attr, extra_fields, min_hits=LONG_TEXT_MIN_HITS):
    """长正文字段检索：SQL 粗筛后，剥离 URL 再按命中的不同关键词数过滤。

    单个关键词（尤其 2-3 字英文/中文）很容易出现在长文档的链接或无关段落里，
    导致整篇文档被误判为相关。这里要求正文（去掉 URL 后）至少命中 min_hits 个
    不同关键词，或在短字段（如标题/文件名）上命中，才算真正相关；并按命中数排序。"""
    if not keywords:
        return []

    # 先用 SQL 在正文或短字段上做宽松粗筛（任一关键词命中即为候选）。
    fields = [getattr(model, text_attr), *extra_fields]
    conditions = [f.contains(kw) for kw in keywords for f in fields]
    stmt = select(model)
    if conditions: stmt = stmt.where(or_(*conditions))
    if kb_ids and hasattr(model, 'kb_id'):
        stmt = stmt.where(model.kb_id.in_(kb_ids))
    r = await db.execute(stmt.limit(50))
    candidates = list(r.scalars().all())

    lowered = [kw.lower() for kw in keywords]
    scored = []
    for item in candidates:
        body = strip_urls(getattr(item, text_attr, "") or "").lower()
        short = " ".join(str(getattr(item, f.key, "") or "") for f in extra_fields).lower()
        body_hits = sum(1 for kw in lowered if kw in body)
        short_hits = sum(1 for kw in lowered if kw in short)
        # 短字段（标题/文件名）命中本身就是强信号，单次命中即保留；
        # 仅靠正文时要求达到 min_hits，过滤掉 URL/边角误匹配。
        if short_hits >= 1 or body_hits >= min_hits:
            scored.append((short_hits * 10 + body_hits, item))

    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:10]]


def _fd(f): return {"id": f.id, "field_name": f.field_name, "display_name": f.display_name, "data_type": f.data_type, "description": f.description}


def _vector_chunks(collection, query, top_k, db_results, text_attr, include_vectors, kb_ids):
    if not include_vectors:
        return []
    try:
        chroma = ChromaStore()
        results = chroma.search(collection, query, top_k=top_k, kb_ids=kb_ids)
        if results:
            # 距离阈值过滤：最近的结果都太远，说明整个集合与查询无关。
            min_d = min(r.get("distance", float("inf")) for r in results)
            if min_d > settings.VECTOR_MIN_DISTANCE_THRESHOLD:
                return []
            max_allowed = min_d + settings.VECTOR_DISTANCE_DELTA
            filtered = [r for r in results if r.get("distance", float("inf")) <= max_allowed]
            if filtered:
                return filtered
    except Exception:
        logger.exception("向量检索失败，降级为数据库关键词结果")
    return [{"id": d.id, "text": getattr(d, text_attr, "")[:500]} for d in db_results[:5]]
