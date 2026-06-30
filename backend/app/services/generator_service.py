import json
import logging
import re
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.llm_service import LLMService
from app.services.prompt_service import PromptService
from app.services.retrieval_service import RetrievalService
from app.services.validation_service import ValidationService
from app.vectorstore.chroma_client import ChromaStore

logger = logging.getLogger(__name__)


class GeneratorService:

    @staticmethod
    async def generate(db: AsyncSession, requirement_text: str, kb_ids: list[str] | None = None) -> dict:
        retrieval = await RetrievalService.retrieve(db, requirement_text, kb_ids=kb_ids)
        historical_cases = await _get_historical_cases(requirement_text, retrieval["query_keywords"], kb_ids)

        system_content, user_content = PromptService.build(
            requirement_text=requirement_text, field_dicts=retrieval["field_dicts"],
            business_rules=retrieval["business_rules"], state_machines=retrieval["state_machines"],
            term_mappings=retrieval["term_mappings"], defect_chunks=retrieval.get("defect_chunks"),
            prd_chunks=retrieval.get("prd_chunks"), historical_cases=historical_cases,
        )

        llm = LLMService()
        raw_output = await llm.generate(system_content, user_content)
        cases = _parse_cases(raw_output)

        warnings = await ValidationService.validate_cases(db, cases)
        if warnings:
            corrected_cases = await _self_correct(llm, system_content, user_content, raw_output, warnings)
            if _has_valid_cases(corrected_cases):
                cases = corrected_cases
                warnings = await ValidationService.validate_cases(db, cases)

        knowledge_counts = {"field_dicts_count": len(retrieval["field_dicts"]), "business_rules_count": len(retrieval["business_rules"]), "state_machines_count": len(retrieval["state_machines"]), "term_mappings_count": len(retrieval["term_mappings"]), "prd_chunks_count": len(retrieval.get("prd_chunks", [])), "defect_chunks_count": len(retrieval.get("defect_chunks", [])), "historical_cases_count": len(historical_cases)}
        knowledge_matches = _knowledge_matches(retrieval, historical_cases)

        return {
            "cases": cases,
            "knowledge_used": knowledge_counts,
            "knowledge_matches": knowledge_matches,
            "validation_warnings": warnings,
        }

    @staticmethod
    async def generate_stream(db: AsyncSession, requirement_text: str, kb_ids: list[str] | None = None) -> AsyncGenerator[dict, None]:
        yield {"type": "progress", "stage": "retrieving", "message": "正在检索知识库..."}
        retrieval = await RetrievalService.retrieve(db, requirement_text, kb_ids=kb_ids)
        historical_cases = await _get_historical_cases(requirement_text, retrieval["query_keywords"], kb_ids)
        kc = {"field_dicts_count": len(retrieval["field_dicts"]), "business_rules_count": len(retrieval["business_rules"]), "state_machines_count": len(retrieval["state_machines"]), "term_mappings_count": len(retrieval["term_mappings"]), "prd_chunks_count": len(retrieval.get("prd_chunks", [])), "defect_chunks_count": len(retrieval.get("defect_chunks", [])), "historical_cases_count": len(historical_cases)}
        yield {"type": "progress", "stage": "constructing", "message": f"检索到 {sum(kc.values())} 条相关知识"}

        system_content, user_content = PromptService.build(requirement_text=requirement_text, field_dicts=retrieval["field_dicts"], business_rules=retrieval["business_rules"], state_machines=retrieval["state_machines"], term_mappings=retrieval["term_mappings"], defect_chunks=retrieval.get("defect_chunks"), prd_chunks=retrieval.get("prd_chunks"), historical_cases=historical_cases)

        yield {"type": "progress", "stage": "generating", "message": "AI正在生成..."}
        llm = LLMService()
        full_output = ""
        async for chunk in llm.generate_stream(system_content, user_content):
            full_output += chunk; yield {"type": "chunk", "text": chunk}

        cases = _parse_cases(full_output)
        yield {"type": "progress", "stage": "validating", "message": "正在校验..."}
        warnings = await ValidationService.validate_cases(db, cases)
        if warnings:
            yield {"type": "progress", "stage": "correcting", "message": f"发现 {len(warnings)} 个问题，正在修正..."}
            corrected_output = ""
            async for chunk in _self_correct_stream(llm, system_content, user_content, full_output, warnings):
                corrected_output += chunk; yield {"type": "chunk", "text": chunk}
            corrected_cases = _parse_cases(corrected_output)
            if _has_valid_cases(corrected_cases):
                cases = corrected_cases
                warnings = await ValidationService.validate_cases(db, cases)

        yield {"type": "complete", "cases": cases, "knowledge_used": kc, "knowledge_matches": _knowledge_matches(retrieval, historical_cases), "validation_warnings": warnings}


def _knowledge_matches(retrieval: dict, historical_cases: list[dict]) -> dict[str, list[dict]]:
    return {
        "field_dicts": [_pick(item, ["id", "field_name", "display_name", "data_type", "description"]) for item in retrieval["field_dicts"]],
        "business_rules": [_pick(item, ["id", "rule_name", "rule_type", "expression", "description"]) for item in retrieval["business_rules"]],
        "state_machines": [_pick(item, ["id", "entity", "from_state", "to_state", "condition"]) for item in retrieval["state_machines"]],
        "term_mappings": [_pick(item, ["id", "ui_term", "tech_field", "mapping_desc"]) for item in retrieval["term_mappings"]],
        "prd_chunks": [_clip_text(item) for item in retrieval.get("prd_chunks", [])],
        "defect_chunks": [_clip_text(item) for item in retrieval.get("defect_chunks", [])],
        "historical_cases": [_clip_text(item) for item in historical_cases],
    }


def _pick(item: dict, fields: list[str]) -> dict:
    result = {}
    for field in fields:
        value = item.get(field)
        if value is not None:
            result[field] = _clip_value(value)
    return result


def _clip_value(value):
    if not isinstance(value, str):
        return value
    return value[:160]


def _clip_text(item: dict) -> dict:
    clipped = _pick(item, ["id", "title", "filename", "score", "distance"])
    text = str(item.get("text") or "")
    if text:
        clipped["text"] = text[:160]
    return clipped


async def _get_historical_cases(text: str, keywords: list[str], kb_ids: list[str] | None = None) -> list[dict]:
    if not keywords:
        return []
    try:
        c = ChromaStore()
        results = [r for r in c.search("historical_cases", text, top_k=3, kb_ids=kb_ids) if r.get("text")]
        if not results:
            return []
        # 与 _vector_chunks 一致的距离阈值过滤：最近的示例都太远说明与需求无关，
        # 否则历史用例会作为 few-shot 把模型带偏（这正是无关需求被"带跑"的根因）。
        min_d = min(r.get("distance", float("inf")) for r in results)
        if min_d > settings.VECTOR_MIN_DISTANCE_THRESHOLD:
            return []
        max_allowed = min_d + settings.VECTOR_DISTANCE_DELTA
        return [{"text": r["text"], "score": r.get("distance", 0)} for r in results if r.get("distance", float("inf")) <= max_allowed]
    except Exception:
        logger.exception("历史用例检索失败，跳过 few-shot 示例")
        return []


def _has_valid_cases(cases: list[dict]) -> bool:
    return any(case.get("title") and not case.get("error") for case in cases)


def _correction_prompt(output: str, warnings: list[dict]) -> str:
    wt = "\n".join(f"- #{w['case_index']} {w['title']}: {'; '.join(w['warnings'])}" for w in warnings[:5])
    return f"请修正以下问题后重新输出完整 JSON 数组：\n{wt}\n\n原始输出：\n{output}"


async def _self_correct(llm, system, user, output, warnings):
    corrected = await llm.generate(system, _correction_prompt(output, warnings))
    return _parse_cases(corrected)


async def _self_correct_stream(llm, system, user, output, warnings):
    async for chunk in llm.generate_stream(system, _correction_prompt(output, warnings)):
        yield chunk


def _parse_cases(raw: str) -> list[dict]:
    try:
        parsed = json.loads(raw)
        cases = _extract_cases(parsed)
        if cases is not None:
            return cases
    except json.JSONDecodeError:
        logger.debug("LLM 输出不是直接可解析的 JSON，尝试从代码块提取")
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m:
        try:
            parsed = json.loads(m.group(1))
            cases = _extract_cases(parsed)
            if cases is not None:
                return cases
        except json.JSONDecodeError:
            logger.debug("代码块中的 LLM 输出不是合法 JSON，尝试提取数组")
    array_cases = _extract_first_array(raw)
    if array_cases is not None:
        return array_cases
    return [{"error": "模型输出格式错误，请重试"}]


def _extract_first_array(raw: str) -> list[dict] | None:
    decoder = json.JSONDecoder()
    start = raw.find("[")
    while start != -1:
        try:
            parsed, _ = decoder.raw_decode(raw[start:])
            cases = _extract_cases(parsed)
            if cases is not None:
                return cases
        except json.JSONDecodeError:
            pass
        start = raw.find("[", start + 1)
    return None


def _extract_cases(parsed) -> list[dict] | None:
    if isinstance(parsed, dict) and "cases" in parsed:
        parsed = parsed["cases"]
    if isinstance(parsed, list):
        return [case for case in parsed if isinstance(case, dict)]
    return None
