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
        # 评审 + 补充：保留好的、删掉有问题的、针对缺口补充，而非整批重写。
        if _has_valid_cases(cases):
            review = await _review_cases(llm, system_content, cases, warnings)
            kept, deleted = _apply_review(cases, review.get("reviews", []))
            if _has_valid_cases(kept):
                cases = kept
            else:
                deleted = []
            gaps = review.get("gaps", [])
            if deleted or gaps:
                supp_output = await _supplement(llm, system_content, cases, deleted, gaps)
                supplements = [c for c in _parse_cases(supp_output) if c.get("title") and not c.get("error")]
                if supplements:
                    cases = cases + supplements
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

        # 评审：以测试专家身份逐条判定保留/删除，不改写已生成的用例。
        if _has_valid_cases(cases):
            yield {"type": "progress", "stage": "reviewing", "message": "测试专家正在评审用例..."}
            review = await _review_cases(llm, system_content, cases, warnings)
            kept, deleted = _apply_review(cases, review.get("reviews", []))
            if _has_valid_cases(kept):
                cases = kept
            else:
                deleted = []  # 评审把用例全删了，判定不可信，全部保留
            gaps = review.get("gaps", [])
            if deleted:
                yield {"type": "progress", "stage": "reviewing", "message": f"评审删除 {len(deleted)} 条问题用例，保留 {len(cases)} 条"}

            # 补充：仅针对被删场景与遗漏场景生成新用例，追加到保留的用例后。
            if deleted or gaps:
                yield {"type": "progress", "stage": "supplementing", "message": "正在补充遗漏场景的用例..."}
                supp_output = ""
                async for chunk in _supplement_stream(llm, system_content, cases, deleted, gaps):
                    supp_output += chunk; yield {"type": "chunk", "text": chunk}
                supplements = [c for c in _parse_cases(supp_output) if c.get("title") and not c.get("error")]
                if supplements:
                    cases = cases + supplements
                    yield {"type": "progress", "stage": "supplementing", "message": f"补充 {len(supplements)} 条用例，共 {len(cases)} 条"}
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


def _case_brief(case: dict, idx: int) -> str:
    """评审用：把一条用例压缩成简短文本，带序号。"""
    steps = case.get("steps", "")
    if isinstance(steps, list):
        steps = "; ".join(str(s) for s in steps)
    return (
        f"#{idx} 【{case.get('priority', '')}】{case.get('title', '')}\n"
        f"   前置：{(case.get('precondition') or '')[:80]}\n"
        f"   步骤：{str(steps)[:160]}\n"
        f"   预期：{(case.get('expected_result') or '')[:120]}"
    )


def _review_prompt(cases: list[dict], warnings: list[dict]) -> str:
    briefs = "\n".join(_case_brief(c, i) for i, c in enumerate(cases))
    warn_text = ""
    if warnings:
        wt = "\n".join(f"- #{w['case_index']} {'; '.join(w['warnings'])}" for w in warnings[:10])
        warn_text = f"\n\n## 自动校验已发现的问题（供参考）\n{wt}"
    return f"""你现在是测试评审专家。请逐条评审下面已生成的测试用例，判断每条是「保留」还是「删除」。

删除标准（满足任一即删）：
- 引用了不存在的字段/规则，或预期结果违反业务规则
- 与其它用例完全重复
- 步骤或预期含糊、不可执行、自相矛盾
- 明显偏离需求

注意：不要改写用例内容，只做保留/删除判断。同时指出整体上还遗漏了哪些应覆盖但当前没有的场景。

## 待评审用例（共 {len(cases)} 条）
{briefs}{warn_text}

只输出如下 JSON（不要 markdown 代码块）：
{{
  "reviews": [{{"index": <用例序号>, "verdict": "keep|delete", "reason": "<简短理由>"}}],
  "gaps": ["<遗漏场景1>", "<遗漏场景2>"]
}}"""


async def _review_cases(llm, system: str, cases: list[dict], warnings: list[dict]) -> dict:
    """调用 LLM 评审，返回 {reviews:[...], gaps:[...]}；失败时返回空（全部保留）。"""
    try:
        raw = await llm.generate(system, _review_prompt(cases, warnings))
        parsed = _parse_json_object(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        logger.exception("用例评审失败，跳过删除与补充")
    return {"reviews": [], "gaps": []}


def _apply_review(cases: list[dict], reviews: list[dict]) -> tuple[list[dict], list[dict]]:
    """按评审结论拆分为保留与删除两组。未被提及的用例默认保留。"""
    delete_idx = {
        r.get("index") for r in reviews
        if isinstance(r, dict) and r.get("verdict") == "delete" and isinstance(r.get("index"), int)
    }
    kept = [c for i, c in enumerate(cases) if i not in delete_idx]
    deleted = [c for i, c in enumerate(cases) if i in delete_idx]
    return kept, deleted


def _supplement_prompt(kept: list[dict], deleted: list[dict], gaps: list[str]) -> str:
    kept_titles = "\n".join(f"- {c.get('title', '')}" for c in kept) or "（无）"
    parts = []
    if deleted:
        parts.append("被删除（需用合格用例覆盖这些场景）：\n" + "\n".join(f"- {c.get('title', '')}" for c in deleted))
    if gaps:
        parts.append("评审指出的遗漏场景：\n" + "\n".join(f"- {g}" for g in gaps))
    todo = "\n\n".join(parts) or "（补充能进一步提升覆盖率的场景）"
    return f"""下面是评审后保留的合格用例标题，请勿重复它们：
{kept_titles}

请只针对以下需要补充的场景，生成新的合格测试用例（不要重复上面已有的，不要重新输出已有用例）：

{todo}

只输出新增用例的 JSON 数组（不要 markdown 代码块），格式与原用例一致（title/priority/precondition/steps/expected_result/knowledge_refs）。若无需补充则输出 []。"""


async def _supplement(llm, system: str, kept: list[dict], deleted: list[dict], gaps: list[str]) -> str:
    return await llm.generate(system, _supplement_prompt(kept, deleted, gaps))


async def _supplement_stream(llm, system: str, kept: list[dict], deleted: list[dict], gaps: list[str]):
    async for chunk in llm.generate_stream(system, _supplement_prompt(kept, deleted, gaps)):
        yield chunk


def _parse_json_object(raw: str) -> dict | None:
    """从 LLM 输出中解析出一个 JSON 对象（容忍 markdown 代码块包裹）。"""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m:
        try:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    start = raw.find("{")
    while start != -1:
        try:
            parsed, _ = decoder.raw_decode(raw[start:])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        start = raw.find("{", start + 1)
    return None


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
