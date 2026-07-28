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
    async def clarify(db: AsyncSession, requirement_text: str, kb_ids: list[str] | None = None) -> str:
        """基于知识库补全（澄清）需求：检索 → LLM 补全 → 返回 Markdown 文本。
        不生成测试用例，只产出结构化的完整需求说明。"""
        retrieval = await RetrievalService.retrieve(db, requirement_text, kb_ids=kb_ids)
        historical_cases = await _get_historical_cases(requirement_text, retrieval["query_keywords"], kb_ids)
        system_content, user_content = PromptService.build_clarify(
            requirement_text=requirement_text, field_dicts=retrieval["field_dicts"],
            business_rules=retrieval["business_rules"], state_machines=retrieval["state_machines"],
            term_mappings=retrieval["term_mappings"], defect_chunks=retrieval.get("defect_chunks"),
            prd_chunks=retrieval.get("prd_chunks"), historical_cases=historical_cases,
        )
        return await LLMService().generate(system_content, user_content)

    @staticmethod
    async def generate_stream(db: AsyncSession, requirement_text: str, kb_ids: list[str] | None = None) -> AsyncGenerator[dict, None]:
        yield {"type": "progress", "stage": "retrieving", "message": "正在检索知识库..."}
        retrieval = await RetrievalService.retrieve(db, requirement_text, kb_ids=kb_ids)
        historical_cases = await _get_historical_cases(requirement_text, retrieval["query_keywords"], kb_ids)
        kc = {"field_dicts_count": len(retrieval["field_dicts"]), "business_rules_count": len(retrieval["business_rules"]), "state_machines_count": len(retrieval["state_machines"]), "term_mappings_count": len(retrieval["term_mappings"]), "prd_chunks_count": len(retrieval.get("prd_chunks", [])), "defect_chunks_count": len(retrieval.get("defect_chunks", [])), "historical_cases_count": len(historical_cases)}
        yield {"type": "progress", "stage": "constructing", "message": f"检索到 {sum(kc.values())} 条相关知识"}

        # 检索一结束就把命中的知识明细推给前端，避免等到 complete 才显示（生成/评审/补充耗时较长）。
        # complete 事件里同样带这两个字段，作为断线重连时的兜底，前端幂等赋值。
        km = _knowledge_matches(retrieval, historical_cases)
        yield {"type": "knowledge", "knowledge_used": kc, "knowledge_matches": km}

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

        yield {"type": "complete", "cases": cases, "knowledge_used": kc, "knowledge_matches": km, "validation_warnings": warnings}


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
    # 空串 = 模型只吐了 reasoning_content 就结束（多为推理强度过高、思考爆了 max_tokens），
    # 一个 JSON 起始符都没有则说明整段都是自然语言（拒答/思考流兜底）。这两种情况都不该
    # 走后面的 JSON 分支——直接给用户可行动的提示，别再让人猜"格式错误"是啥意思。
    if not raw or ("{" not in raw and "[" not in raw):
        logger.warning("LLM 未产出结构化正文（len=%d），可能是推理强度过高或 max_tokens 不足", len(raw))
        return [{"error": "模型只输出了思考过程未产出用例（建议调低 LLM_REASONING_EFFORT 或调大 LLM_MAX_TOKENS）"}]
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
    # 合法空结果：模型正确判定"无可测内容"，返回了 {"cases": []} 并在 gaps 里说明原因
    # （典型：需求过于简单/无功能点）。这不是格式错误，把原因透传给用户，别误报"请重试"。
    empty_reason = _empty_result_reason(raw)
    if empty_reason is not None:
        logger.info("LLM 判定无可测内容，未生成用例：%s", empty_reason)
        return [{"error": empty_reason}]
    # 前面几条路径都失败，通常是响应被 max_tokens 截断导致 JSON 未闭合。
    # 用 raw_decode 逐个抓取已闭合的 case 对象，保住已经完整生成的部分，避免整批丢失。
    salvaged = _salvage_truncated_cases(raw)
    if salvaged:
        logger.warning("LLM 输出疑似被截断，抢救出 %s 条完整用例（考虑调大 LLM_MAX_TOKENS）", len(salvaged))
        return salvaged
    # 所有路径都失败：把 raw 的规模与首尾片段打出来，区分空串 / 拒答文本 / 完全非 JSON 的失败模式。
    # 之前只 debug 级别 log，等于什么线索都没有，复现一次要猜半天。
    logger.warning(
        "LLM 输出无法解析为用例数组（len=%d, head=%r, tail=%r）",
        len(raw), raw[:200], raw[-200:] if len(raw) > 200 else "",
    )
    return [{"error": "模型输出格式错误，请重试"}]


def _empty_result_reason(raw: str) -> str | None:
    """识别"模型合法地判定无可测内容"的空结果，返回面向用户的原因说明。

    模型对无功能点的需求（如"哈哈哈"）会正确返回 {"cases": [], "coverage": {"gaps": [...]}}
    这类空数组结果。此前解析器只认"含 title 的非空数组"，会把这种情况误报成"格式错误，请重试"，
    误导用户以为是系统故障。这里在解析末端兜底：只有当 raw 是合法 JSON 对象、且 cases 显式为空数组
    时才判定为空结果（返回非 None），从 gaps / coverage.gaps 提取原因；无法确认则返回 None，
    交回上层继续走截断抢救等后续路径。
    """
    parsed = _parse_json_object(raw)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("cases"), list) or parsed["cases"]:
        return None
    gaps = parsed.get("gaps")
    if not isinstance(gaps, list) or not gaps:
        coverage = parsed.get("coverage")
        gaps = coverage.get("gaps") if isinstance(coverage, dict) else None
    if isinstance(gaps, list) and gaps:
        reason = "；".join(str(g) for g in gaps if g)
        if reason:
            return f"未生成用例：{reason}"
    return "未生成用例：模型判定该需求无可提取的可测功能点，请补充更明确的功能描述后重试"


def _salvage_truncated_cases(raw: str) -> list[dict]:
    """从残缺的 LLM 输出里逐个抓完整的 case 对象。

    典型触发场景：LLM 已经吐了 N 条完整用例 + 半条不完整，然后被 max_tokens 截断，
    整个数组/代码块都没闭合。这时 json.loads 整体解析必然失败，但每一条完整的
    case 对象本身还是合法 JSON，json.JSONDecoder.raw_decode 可以从任意位置起解一个对象。

    策略：把光标定位到第一个 `{`，然后循环 raw_decode + 跳到下一个 `{`。
    丢弃解不出来的位置（最后那条不完整的 case），只保留 case-like 的 dict（含 title）。
    """
    decoder = json.JSONDecoder()
    cases: list[dict] = []
    i = raw.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(raw[i:])
        except json.JSONDecodeError:
            # 当前位置解不出来（比如是最后不完整的那条）—— 跳到下一个 `{` 重试。
            i = raw.find("{", i + 1)
            continue
        if isinstance(obj, dict) and "title" in obj:
            cases.append(obj)
        # 从这个对象结束的位置继续找下一个 `{`，跳过内部嵌套避免误抓。
        i = raw.find("{", i + end)
    return cases


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
        cases = [case for case in parsed if isinstance(case, dict)]
        if cases and any("title" in c for c in cases):
            return cases
    return None
