import asyncio
import logging
import time
from dataclasses import dataclass
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.llm_service import LLMService
from app.services.prompt_service import PromptService
from app.services.retrieval_service import RetrievalService
from app.services.validation_service import ValidationService
from app.utils.case_grouping import merge_supplements, title_path, title_prefix
from app.utils.case_ordering import order_cases
from app.utils.llm_parsing import parse_cases, parse_json_object, salvage_reviews
from app.utils import token_usage
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
            **_prompt_kwargs(requirement_text, retrieval, historical_cases)
        )
        with token_usage.stage(token_usage.STAGE_CLARIFY):
            return await LLMService().generate(system_content, user_content)

    @staticmethod
    async def generate_stream(db: AsyncSession, requirement_text: str, kb_ids: list[str] | None = None) -> AsyncGenerator[dict, None]:
        """完整生成流水线：检索 → 生成 → 校验+评审 → 补充 → 收口排序。

        每个阶段是一个独立的 async generator：自己 yield 前端事件，产物用 _results 事件
        回传（与 _parallel_agents 同一约定）。本函数只负责串阶段、转发事件、做阶段间判定，
        不掺任何阶段内部细节。
        """
        # 记录整体开始时间，complete 事件里回传总耗时（秒）。
        started_at = time.monotonic()
        yield {"type": "progress", "stage": "retrieving", "message": "正在检索知识库..."}
        ctx = await _build_context(db, requirement_text, kb_ids)
        yield {"type": "progress", "stage": "constructing",
               "message": f"检索到 {sum(ctx.knowledge_used.values())} 条相关知识"}

        # 检索一结束就把命中的知识明细推给前端，避免等到 complete 才显示（生成/评审/补充耗时较长）。
        # complete 事件里同样带这两个字段，作为断线重连时的兜底，前端幂等赋值。
        yield {"type": "knowledge", "knowledge_used": ctx.knowledge_used,
               "knowledge_matches": ctx.knowledge_matches}

        all_cases: list[dict] = []
        async for ev in _stage_generate(ctx):
            if ev["type"] == "_results":
                all_cases = ev["results"]
            else:
                yield ev

        # 没有任何有效用例（解析失败 / 模型合法空结果 / 只思考未输出）：这不是"成功生成 0 条"，
        # 而是一次失败。作为 error 事件抛给前端并 return——既让前端显示明确原因（而非"成功，共 1 条"），
        # 又因为不 emit complete，task_service 不会把 error 占位用例落库污染历史。
        if not _has_valid_cases(all_cases):
            reason = next((c.get("error") for c in all_cases if c.get("error")), None) \
                or "未生成任何有效用例，请补充更明确的需求描述后重试"
            yield {"type": "error", "message": reason}
            return
        # 走到这里说明至少有一条有效用例：把「为什么这批为空」的原因占位剔掉。模块并行下
        # 部分模块解析失败会各留一条占位，它们只服务于上面的失败分支，绝不能流进评审分组、
        # 补充 prompt 与 complete 事件（persist_cases 那道防线不该是唯一的防线）。
        all_cases = [c for c in all_cases if not c.get("error")]

        deleted: list[dict] = []
        gaps: list = []
        async for ev in _stage_review(db, ctx, all_cases):
            if ev["type"] == "_results":
                all_cases, deleted, gaps = ev["results"]
            else:
                yield ev

        if deleted or gaps:
            async for ev in _stage_supplement(ctx, all_cases, deleted, gaps):
                if ev["type"] == "_results":
                    all_cases = ev["results"]
                else:
                    yield ev

        # 收口排序：让补充用例挨到相关功能点旁边。必须放在补充合并之后——补充用例正是
        # 要归位的对象。只挪补充用例（is_movable），原有用例位置一律不动——路径层与
        # 功能点层都受此约束（只在功能点层拦不住：路径排序自己就会把交错的同路径用例并段）。
        # LLM 一次产出的用例本就按功能点聚好（实测 350 个子功能路径仅 6 个被拆段），
        # 而功能点判定靠字面共同前缀这一启发式，动原有用例收益小、误吸附风险大。
        # 顶层模块顺序不受影响：all_cases 已按切割模块下标拼接，order_cases 只识别
        # 块边界、不重排块序。
        all_cases = order_cases(all_cases, lambda c: c.get("title") or "",
                                lambda c: c.get("origin") == "supplement")

        yield {"type": "complete", "cases": all_cases, "knowledge_used": ctx.knowledge_used,
               "knowledge_matches": ctx.knowledge_matches,
               "elapsed": round(time.monotonic() - started_at, 1)}


@dataclass
class _Context:
    """一次生成里跨阶段共享的检索结果与 prompt 上下文。

    base_system 只构造一次、后续所有 LLM 调用（生成/评审/补充）复用：知识库上下文全在
    system 里，各阶段只换 user。
    """
    requirement_text: str
    retrieval: dict
    historical_cases: list[dict]
    knowledge_used: dict[str, int]
    knowledge_matches: dict[str, list[dict]]
    base_system: str


def _prompt_kwargs(requirement_text: str, retrieval: dict, historical_cases: list[dict]) -> dict:
    """PromptService.build / build_clarify 共用的知识库入参（两者这部分签名一致）。
    集中在一处，新增一类检索知识时不必再逐个调用点补参数。"""
    return {
        "requirement_text": requirement_text,
        "field_dicts": retrieval["field_dicts"],
        "business_rules": retrieval["business_rules"],
        "state_machines": retrieval["state_machines"],
        "term_mappings": retrieval["term_mappings"],
        "defect_chunks": retrieval.get("defect_chunks"),
        "prd_chunks": retrieval.get("prd_chunks"),
        "historical_cases": historical_cases,
    }


async def _build_context(db: AsyncSession, requirement_text: str,
                         kb_ids: list[str] | None) -> _Context:
    """检索知识库 + 历史用例，顺带算好推给前端的命中统计与明细。"""
    retrieval = await RetrievalService.retrieve(db, requirement_text, kb_ids=kb_ids)
    historical_cases = await _get_historical_cases(requirement_text, retrieval["query_keywords"], kb_ids)
    base_system, _ = PromptService.build(**_prompt_kwargs(requirement_text, retrieval, historical_cases))
    return _Context(
        requirement_text=requirement_text,
        retrieval=retrieval,
        historical_cases=historical_cases,
        knowledge_used={
            "field_dicts_count": len(retrieval["field_dicts"]),
            "business_rules_count": len(retrieval["business_rules"]),
            "state_machines_count": len(retrieval["state_machines"]),
            "term_mappings_count": len(retrieval["term_mappings"]),
            "prd_chunks_count": len(retrieval.get("prd_chunks", [])),
            "defect_chunks_count": len(retrieval.get("defect_chunks", [])),
            "historical_cases_count": len(historical_cases),
        },
        knowledge_matches=_knowledge_matches(retrieval, historical_cases),
        base_system=base_system,
    )


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
        results = [r for r in await asyncio.to_thread(
            c.search, "historical_cases", text, 3, kb_ids
        ) if r.get("text")]
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


async def _extract_modules(llm, requirement_text: str, prd_chunks: list[dict] | None) -> list[str] | None:
    """阶段1：让 LLM 抽取【模块清单】。失败或无法确认时返回 None（上层退化为单批）。

    模块拆分是「优化层」，其失败绝不能阻断生成——抽取异常、解析失败、模型判定
    覆盖不全（covers_all=false）时，一律返回 None 回退到单批续写式，只打告警日志。
    """
    try:
        system, user = PromptService.build_module_split(requirement_text, prd_chunks)
        with token_usage.stage(token_usage.STAGE_MODULE_SPLIT):
            raw = await llm.generate(system, user)
        parsed = parse_json_object(raw, require_key="modules")
        if not isinstance(parsed, dict):
            logger.warning("模块拆分未返回合法 JSON，退化为单批生成")
            return None
        modules = parsed.get("modules")
        if not isinstance(modules, list):
            logger.warning("模块拆分结果缺少 modules 数组，退化为单批生成")
            return None
        # 去空、去重、保序
        clean: list[str] = []
        for m in modules:
            name = str(m).strip()
            if name and name not in clean:
                clean.append(name)
        # 模型自报未覆盖全部章节：模块分批可能漏用例，宁可退化为单批（单批不会漏模块）。
        if parsed.get("covers_all") is False:
            logger.warning("模块拆分自报未覆盖全部章节（reason=%s），退化为单批生成以防漏模块", parsed.get("reason"))
            return None
        return clean or None
    except Exception:
        logger.exception("模块拆分调用失败，退化为单批生成")
        return None


async def _stage_generate(ctx: _Context) -> AsyncGenerator[dict, None]:
    """阶段①：模块拆分（可选）→ 分模块并行生成 / 单批生成 → 跨批去重。_results 回传用例列表。"""
    llm = LLMService()
    # 仅在 LLM_ENABLE_MODULE_SPLIT 开启、且需求文本足够长时才抽取模块清单。
    # 小需求（< LLM_MODULE_SPLIT_MIN_CHARS）跳过：单批生成本就撑不满 max_tokens，
    # 抽模块只会白花一次 LLM 调用；且续写式兜底始终生效，跳过不影响防截断。
    modules = None
    if settings.LLM_ENABLE_MODULE_SPLIT and len(ctx.requirement_text) >= settings.LLM_MODULE_SPLIT_MIN_CHARS:
        yield {"type": "progress", "stage": "splitting", "message": "正在分析模块结构..."}
        modules = await _extract_modules(llm, ctx.requirement_text, ctx.retrieval.get("prd_chunks"))
        if not modules or len(modules) <= 1:
            modules = None  # 一个模块或没有，退化为单批

    all_cases: list[dict] = []
    if modules:
        async for ev in _generate_by_modules(ctx, modules):
            if ev["type"] == "_results":
                # 按模块下标顺序拼接，抹平并发完成时序带来的乱序；失败的模块为 None。
                for batch in ev["results"]:
                    all_cases.extend(batch or [])
            else:
                yield ev
    else:
        # 无模块分批：单批生成 + 续写兜底
        yield {"type": "progress", "stage": "generating", "message": "AI正在生成..."}
        all_cases = await _generate_one_batch(llm, ctx, module_focus=None, existing_titles=[])

    # ── 跨批去重（按 title 归一化后精确匹配） ──
    if len(all_cases) > 1:
        deduped = _dedup_by_title(all_cases)
        if len(deduped) < len(all_cases):
            logger.info("去重合并：%d → %d 条", len(all_cases), len(deduped))
        all_cases = deduped
    yield {"type": "_results", "results": all_cases}


async def _generate_by_modules(ctx: _Context, modules: list[str]) -> AsyncGenerator[dict, None]:
    """分模块并行生成：每个模块一个 agent、一张卡片实时流，_results 按模块下标顺序回传各批。

    跨模块的 title 去重不实时共享（并发下无法安全共享可变列表），改由上层在全部完成后用
    _dedup_by_title 按归一化 title 统一精确去重。
    """
    total = len(modules)
    # 把拆分出的模块清单推给前端，让用户看到「本次拆成了哪些模块」，
    # 而不是只显示"正在分析模块结构..."后就闷头生成（此前无从得知拆了什么）。
    yield {"type": "modules", "modules": modules}
    yield {"type": "progress", "stage": "generating",
           "message": f"已拆分为 {total} 个模块，开始并行生成：{('、'.join(modules))[:120]}"}
    done_count = 0
    async for ev in _parallel_agents(
        [{"module": m} for m in modules],
        lambda i, item, emit: _module_worker(i, item, emit, ctx),
        phase="module",
    ):
        yield ev
        if ev["type"] in ("module_done", "module_failed"):
            done_count += 1
            suffix = f"（模块「{ev['module']}」失败已跳过）" if ev["type"] == "module_failed" \
                else f"：{ev['module']}"
            yield {"type": "progress", "stage": "generating",
                   "message": f"模块生成进度 {done_count}/{total}{suffix}"}


async def _module_worker(idx: int, item: dict, emit, ctx: _Context) -> tuple[list[dict], dict]:
    """生成单个模块的用例。返回的用例随 done 事件下发（前端用它把卡片从「流式文本」
    切换为解析好的用例列表）。

    每个模块用独立的 LLMService 实例——续写兜底依赖实例上的 last_finish_reason 状态，
    共享一个实例会互相覆盖导致判断错乱。
    """
    module = item["module"]

    async def on_chunk(text: str) -> None:
        # 该模块的实时正文流：带 index，前端归档到对应 agent 卡片。
        await emit("chunk", {"text": text})

    async def on_reasoning(text: str) -> None:
        # 思考流用独立事件类型，前端在思考阶段展示 🤔 思考中，避免干等"等待模型输出"。
        await emit("thinking", {"text": text})

    batch = await _generate_one_batch(LLMService(), ctx, module_focus=module, existing_titles=[],
                                      on_chunk=on_chunk, on_reasoning=on_reasoning)
    # 回传给上层的 batch 可能是一条无 title 的 `{"error": 原因}` 占位（本模块一条都没解析出来），
    # 它只用于「全部模块都空」时向用户解释原因；下发前端的 cases 必须剔掉它，否则卡片会
    # 渲染出一条空白用例。
    valid = [c for c in batch if not c.get("error")]
    if valid:
        logger.info("模块[%s]生成 %d 条用例", module, len(valid))
    return batch, {"cases": valid}


async def _generate_one_batch(
    llm, ctx: _Context, module_focus: str | None, existing_titles: list[str],
    on_chunk=None, on_reasoning=None,
) -> list[dict]:
    """生成一批用例，内含「续写式」兜底：撞满 max_tokens 就带着已有 title 续写，
    循环到 finish_reason != length 或达到 LLM_MAX_CONTINUATIONS 上限。

    existing_titles 会被就地追加本批新生成的 title（供续写防重复）。
    module_focus 非空时按该模块聚焦生成，为 None 则是不分模块的单批。
    on_chunk 非空时，每收到一段流式文本就以其为参数调用（可为 async），供上层按模块
    实时展示该 agent 的输出流。

    返回本批解析出的用例列表。一条有效用例都没解析出来时，返回单条无 title 的
    `[{"error": 原因}]` 占位——把 parse_cases 给出的可行动原因（"调低推理强度" /
    "需求无可测功能点"）带给上层组装 error 事件，别让它退化成笼统一句"生成失败"。
    """
    _, user_content = PromptService.build(
        **_prompt_kwargs(ctx.requirement_text, ctx.retrieval, ctx.historical_cases),
        module_focus=module_focus,
    )

    batch_cases: list[dict] = []
    # 只留**首轮**的原因：续写轮的失败（如已写完后再问一次得到空串）说明不了本批为何为空。
    empty_reason: str | None = None
    cur_user = user_content
    for attempt in range(settings.LLM_MAX_CONTINUATIONS + 1):
        # 流式收取：边收边把原始文本通过 on_chunk 推给上层展示，同时累积成整段
        # 供后续 parse_cases 解析。相比一次性 generate()，用户能看到 agent 实时吐字。
        parts: list[str] = []
        with token_usage.stage(token_usage.STAGE_GENERATE):
            async for piece in llm.generate_stream(ctx.base_system, cur_user, on_reasoning=on_reasoning):
                parts.append(piece)
                if on_chunk is not None and piece:
                    res = on_chunk(piece)
                    if asyncio.iscoroutine(res):
                        await res
        raw = "".join(parts)
        parsed = parse_cases(raw)
        cases = [c for c in parsed if c.get("title") and not c.get("error")]
        if empty_reason is None:
            empty_reason = next((c.get("error") for c in parsed if c.get("error")), None)
        # 只累加"未出现过的 title"，避免续写时模型重复吐已有用例。
        for c in cases:
            key = _title_key(c.get("title", ""))
            if key and key not in {_title_key(t) for t in existing_titles}:
                batch_cases.append(c)
                existing_titles.append(c.get("title", ""))

        # 未被截断：本批正常结束。
        if llm.last_finish_reason != "length":
            break
        # 被截断且还有续写额度：带上已有 title 续写。
        if attempt < settings.LLM_MAX_CONTINUATIONS:
            logger.warning(
                "模块[%s]第 %d 轮被 max_tokens 截断（已累计 %d 条），继续续写",
                module_focus or "单批", attempt + 1, len(existing_titles),
            )
            cur_user = PromptService.build_continuation(existing_titles)
        else:
            logger.warning(
                "模块[%s]续写达到上限 %d 轮仍被截断，停止续写（已累计 %d 条）",
                module_focus or "单批", settings.LLM_MAX_CONTINUATIONS, len(existing_titles),
            )
    if not batch_cases and empty_reason:
        return [{"error": empty_reason}]
    return batch_cases


def _title_key(title: str) -> str:
    """title 归一化：去首尾空白 + 全角转半角 + 内部空白折叠，用于跨批精确去重。"""
    if not title:
        return ""
    # 全角空格/标点常见变体归一（只处理空白，避免误伤业务语义）
    t = title.replace("　", " ").strip()
    return " ".join(t.split())


def _dedup_by_title(cases: list[dict]) -> list[dict]:
    """按归一化 title 精确去重，保留首次出现的用例（保序）。"""
    seen: set[str] = set()
    result: list[dict] = []
    for c in cases:
        key = _title_key(c.get("title", ""))
        if not key:
            result.append(c)  # 无 title 的（如 error 占位）不参与去重，原样保留
            continue
        if key in seen:
            continue
        seen.add(key)
        result.append(c)
    return result


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
    return f"""你现在是测试评审专家。请逐条评审下面已生成的测试用例，挑出其中**应当删除**的。

删除标准（满足任一即删）：
- 引用了不存在的字段/规则，或预期结果违反业务规则
- 与其它用例完全重复
- 步骤或预期含糊、不可执行、自相矛盾
- 明显偏离需求

注意：不要改写用例内容，只做删除判断。同时指出整体上还遗漏了哪些应覆盖但当前没有的场景。

## 待评审用例（共 {len(cases)} 条）
{briefs}{warn_text}

**只列出要删除的用例**，判定保留的一律不要输出——未列出的自动视为保留。逐条输出 keep
会让响应长度随用例数线性膨胀、撑满 token 上限，一旦被截断，后面所有判定都会丢失。
index 必须照抄上面每条用例前的 #编号，不要自己重新数。

只输出如下 JSON（不要 markdown 代码块）：
{{
  "reviews": [{{"index": <用例序号>, "verdict": "delete", "reason": "<简短理由>"}}],
  "gaps": ["<遗漏场景1>", "<遗漏场景2>"]
}}"""


async def _parallel_agents(items: list[dict], worker_factory, phase: str):
    """通用「多 agent 并行 + 每 agent 卡片实时流」运行器（评审/补充共用）。

    items: 任务列表，每项是 dict，至少含 "module"（卡片标题）。
    worker_factory(idx, item, emit) -> 协程，返回 (result, summary)：
      - result：该 agent 的产物（评审 dict / 补充 list），最终经 _results 事件回传给上层收口。
      - summary：dict，随 done 事件下发前端展示（评审给 kept/deleted，补充给 count）。
      - emit(kind, extra) 把流事件推给前端：kind ∈ {thinking, chunk}，
        最终以 f"{phase}_{kind}" 作为事件 type，带 index。
    phase: 事件类型前缀（"review" / "supplement"），前端据此归档到对应卡片区。

    与生成阶段共用同一套限流：受 LLM_MODULE_CONCURRENCY 并发上限约束，按
    LLM_MODULE_STAGGER_DELAY 错峰启动，避免评审/补充突刺撞到套餐限流。
    汇流队列单点消费，多 agent 的流不会在 yield 层交错。
    """
    total = len(items)
    if not total:
        yield {"type": "_results", "results": []}
        return

    sem = asyncio.Semaphore(max(1, settings.LLM_MODULE_CONCURRENCY))
    stagger = max(0.0, settings.LLM_MODULE_STAGGER_DELAY)
    event_q: asyncio.Queue = asyncio.Queue()
    results: list = [None] * total

    async def _run(idx: int, item: dict) -> None:
        if stagger and idx:
            await asyncio.sleep(idx * stagger)
        async with sem:
            started = time.monotonic()
            module = item.get("module", "")
            await event_q.put({"kind": "start", "index": idx, "module": module})

            async def emit(kind: str, extra: dict | None = None) -> None:
                ev = {"kind": kind, "index": idx}
                if extra:
                    ev.update(extra)
                await event_q.put(ev)

            try:
                res, summary = await worker_factory(idx, item, emit)
            except Exception:
                logger.exception("并行 agent[%s] 失败", module or idx)
                await event_q.put({"kind": "failed", "index": idx, "module": module,
                                   "elapsed": round(time.monotonic() - started, 1)})
                return
            results[idx] = res
            done_ev = {"kind": "done", "index": idx, "module": module,
                       "elapsed": round(time.monotonic() - started, 1)}
            done_ev.update(summary or {})
            await event_q.put(done_ev)

    tasks = [asyncio.create_task(_run(i, it)) for i, it in enumerate(items)]
    done_count = 0
    while done_count < total:
        ev = await event_q.get()
        kind = ev.pop("kind")
        if kind in ("done", "failed"):
            done_count += 1
        out = {"type": f"{phase}_{kind}"}
        out.update(ev)
        yield out
    await asyncio.gather(*tasks, return_exceptions=True)
    yield {"type": "_results", "results": results}


async def _stage_review(db: AsyncSession, ctx: _Context,
                        cases: list[dict]) -> AsyncGenerator[dict, None]:
    """阶段②：自动校验 + 分模块并行评审。_results 回传 (保留的用例, 被删用例, 遗漏场景)。

    评审以测试专家身份逐条判定保留/删除，不改写已生成的用例。按【模块】把用例分组，每组
    一个独立评审 agent 并行跑，每个 agent 一张卡片实时流式展示评审过程，用户能看到
    「AI 正在保留/删除哪条、理由是什么」，而不是干等一句静态提示。

    校验必须在这里跑（评审之前）：告警按用例下标引用，要与评审分组用的是同一份列表下标。
    """
    yield {"type": "progress", "stage": "validating", "message": "正在校验..."}
    warnings = await ValidationService.validate_cases(db, cases)

    yield {"type": "progress", "stage": "reviewing", "message": "测试专家正在分模块并行评审用例..."}
    warnings_by_global = {
        w["case_index"]: w for w in warnings if isinstance(w.get("case_index"), int)
    }
    reviews: list[dict] = []
    gaps: list = []
    async for ev in _parallel_agents(
        _group_by_module(cases),
        lambda i, g, emit: _review_worker(i, g, emit, ctx.base_system, warnings_by_global),
        phase="review",
    ):
        if ev["type"] == "_results":
            for r in ev["results"]:
                if isinstance(r, dict):
                    reviews.extend(r.get("reviews", []))
                    gaps.extend(r.get("gaps", []))
        else:
            yield ev

    kept, deleted = _apply_review(cases, reviews)
    if _has_valid_cases(kept):
        cases = kept
    else:
        deleted = []  # 评审把用例全删了，判定不可信，全部保留
    if deleted:
        yield {"type": "progress", "stage": "reviewing",
               "message": f"评审删除 {len(deleted)} 条问题用例，保留 {len(cases)} 条"}
    yield {"type": "_results", "results": (cases, deleted, gaps)}


async def _stage_supplement(ctx: _Context, cases: list[dict], deleted: list[dict],
                            gaps: list[str]) -> AsyncGenerator[dict, None]:
    """阶段③：把被删场景按模块分组、遗漏场景单独一组，每组一个补充 agent 并行生成，各自
    一张卡片实时流式展示。生成后跨 agent + 与保留用例统一按 title 去重再合并。
    _results 回传合并后的用例列表。"""
    yield {"type": "progress", "stage": "supplementing", "message": "正在分模块并行补充遗漏场景的用例..."}
    collected: list[dict] = []
    async for ev in _parallel_agents(
        _build_supplement_tasks(deleted, gaps),
        lambda i, it, emit: _supplement_worker(i, it, emit, ctx.base_system, cases),
        phase="supplement",
    ):
        if ev["type"] == "_results":
            for r in ev["results"]:
                if isinstance(r, list):
                    collected.extend(r)
        else:
            yield ev
    # 跨 agent + 与已保留用例统一去重（并行下无法实时共享 title，完成后统一收口）。
    existing = {_title_key(c.get("title", "")) for c in cases}
    supplements: list[dict] = []
    for c in collected:
        k = _title_key(c.get("title", ""))
        if k and k not in existing:
            existing.add(k)
            # 打上产出阶段标记，落库进 test_cases.origin，前端据此显示「补充」标签。
            # 必须在这里打：合并后补充用例会散到各自模块里，事后再也分不出来
            # （生成/补充用例的 source 都是 'ai'，created_at 只是写库时间）。
            supplements.append({**c, "origin": "supplement"})
    if supplements:
        cases = merge_supplements(cases, supplements)
        yield {"type": "progress", "stage": "supplementing",
               "message": f"补充 {len(supplements)} 条用例，共 {len(cases)} 条"}
    yield {"type": "_results", "results": cases}


def _group_by_module(cases: list[dict]) -> list[dict]:
    """按标题【】里的模块路径把用例分组，保留每条用例的全局下标（供评审结论映射回整批）。
    无模块前缀的归入「其它」。返回 [{"module": 名, "items": [(global_idx, case), ...]}]。

    顶层（第 1 级）一律先分组——「评审按模块并行、每模块一张流式卡片」是既有设计，
    小需求也不该退化成一张名叫「其它」的大卡片。之后**由条数驱动**决定要不要继续下钻：
    只有超过 LLM_REVIEW_BATCH_SIZE 的组才按下一级路径细分，装得下的组整体保留。

    深度只是手段、不能写死。曾写死「取前两级」，那是错的——路径有几级取决于该 PRD
    恰好覆盖几个平台。这批需求含 PC/移动端两个平台，顶层是平台名，取两级刚好
    （17 组、最大 107 条）；而单平台需求根本不出现平台名、顶层就是功能模块，同样取
    两级会一路钻到页面/区块级，实测炸成 178 组、其中 121 个 ≤5 条的碎组
    （`我的任务-分页` 只剩 1 条），并发 5 下要跑 36 波。改为按条数驱动后两种形状都稳：
    这批 16 组，单平台模拟 15 组，且碎组不再由我们制造。

    路径已无更深一级（或整组同属一个子路径）却仍超限时，最后才按条数均分切块。
    """
    cap = max(1, settings.LLM_REVIEW_BATCH_SIZE)
    top: dict[str, list[tuple[int, dict]]] = {}
    for i, c in enumerate(cases):
        path = title_path(c.get("title", ""))
        top.setdefault(path[0] if path else "其它", []).append((i, c))
    out: list[dict] = []
    for name, items in top.items():
        _split_module_group(name, items, 2, cap, out)
    return out


def _split_module_group(name: str, items: list[tuple[int, dict]], depth: int,
                        cap: int, out: list[dict]) -> None:
    """把一个模块分组递归拆到不超过 cap 条，结果按序 append 进 out。

    name: 当前分组名。depth: 本层按路径的第几级细分（顶层已分完，故从 2 起）。
    终止性：每次递归要么把 items 切成 ≥2 份且每份更小，要么保持条数但让分组名严格
    多一级（受最长路径长度所限），故必然收敛。
    """
    if len(items) <= cap:
        out.append({"module": name, "items": items})
        return
    sub: dict[str, list[tuple[int, dict]]] = {}
    for gi, c in items:
        path = title_path(c.get("title", ""))
        # 路径不够深的用例留在当前层自成一组，别硬塞进某个更深的子路径。
        key = "-".join(path[:depth]) if len(path) >= depth else name
        sub.setdefault(key, []).append((gi, c))
    if len(sub) > 1:
        for k, v in sub.items():
            _split_module_group(k, v, depth + 1, cap, out)
        return
    # 只有一个子节点：沿着这条单链继续下钻，别在这里就退化成条数切块。整组同属一个
    # 更深的子路径时，下一级往往才是有区分度的那一层——若某顶层 629 条全在同一个二级
    # 模块下，就地切块会得到 `PC (1/4)` 这种任意边界，正是本次要消灭的东西。
    only_key = next(iter(sub))
    if only_key != name:
        _split_module_group(only_key, items, depth + 1, cap, out)
        return
    # 路径确实到底了（key 已等于当前组名，再深也分不出东西），只能按条数兜底切块。
    # 均分而非按 cap 贪心：500 条按 cap=200 贪心会切出 200/200/100，最后那块明显偏小
    # 却同样白占一次 LLM 调用和一张卡片；先算块数再均分得到 167/167/166。
    n_chunks = -(-len(items) // cap)
    size = -(-len(items) // n_chunks)
    chunks = [items[s:s + size] for s in range(0, len(items), size)]
    for n, chunk in enumerate(chunks, 1):
        out.append({"module": f"{name} ({n}/{len(chunks)})", "items": chunk})


async def _review_worker(idx: int, group: dict, emit, system: str,
                         warnings_by_global: dict[int, dict]) -> tuple[dict, dict]:
    """评审单个模块分组：流式吐评审 JSON（思考流经 emit 实时下发），解析后把每条 review
    的局部 index 映射回全局下标。返回 ({reviews, gaps}, {kept, deleted[, truncated]})
    供上层收口/展示。新契约下模型只列待删条目，未列出的由 _apply_review 默认保留。"""
    items = group["items"]  # [(global_idx, case), ...]
    local_cases = [c for _, c in items]
    # 该组的校验告警按局部下标重映射，保证 prompt 里的 #编号与该组用例对齐。
    local_warnings = []
    for local_i, (gi, _) in enumerate(items):
        w = warnings_by_global.get(gi)
        if w:
            local_warnings.append({**w, "case_index": local_i})

    async def on_reasoning(text: str) -> None:
        if text:
            await emit("thinking", {"text": text})

    parts: list[str] = []
    llm = LLMService()
    with token_usage.stage(token_usage.STAGE_REVIEW):
        async for piece in llm.generate_stream(system, _review_prompt(local_cases, local_warnings),
                                               on_reasoning=on_reasoning):
            parts.append(piece)
            if piece:
                await emit("chunk", {"text": piece})

    raw = "".join(parts)
    # 截断检测：生成阶段撞满 max_tokens 会走续写兜底，评审此前什么都不做——JSON 不闭合、
    # 解析失败，整组判定静默按「全部保留」处理（前端卡片里却已经流过 delete 的判定，
    # 于是"评审说删了但用例还在"）。这里显式识别并抢救已经判完的那部分。
    truncated = llm.last_finish_reason == "length"
    parsed = parse_json_object(raw, require_key="reviews")
    raw_reviews = parsed.get("reviews") if isinstance(parsed, dict) else None
    if not isinstance(raw_reviews, list):
        raw_reviews = salvage_reviews(raw)
        if raw_reviews:
            logger.warning("评审[%s]输出%s，抢救出 %d 条判定（考虑调小 LLM_REVIEW_BATCH_SIZE）",
                           group["module"], "被截断" if truncated else "无法整体解析", len(raw_reviews))
        else:
            logger.warning("评审[%s]输出无法解析（truncated=%s, len=%d, tail=%r），该组用例全部按保留处理",
                           group["module"], truncated, len(raw), raw[-200:])

    reviews: list[dict] = []
    unusable = 0
    for r in raw_reviews:
        if not isinstance(r, dict) or not isinstance(r.get("index"), int) or not 0 <= r["index"] < len(items):
            unusable += 1
            continue
        reviews.append({**r, "index": items[r["index"]][0]})  # 局部 → 全局
    if unusable:
        # 模型自己数错 #编号（越界）或漏了 index 字段时，此前是静默丢弃，等于判定白做。
        logger.warning("评审[%s]有 %d 条判定的 index 缺失或越界，已忽略", group["module"], unusable)
    gaps: list = []
    if isinstance(parsed, dict):
        raw_gaps = parsed.get("gaps", [])
        gaps = raw_gaps if isinstance(raw_gaps, list) else []
    deleted = sum(1 for r in reviews if r.get("verdict") == "delete")
    summary = {"kept": len(items) - deleted, "deleted": deleted}
    if truncated:
        summary["truncated"] = True
    return {"reviews": reviews, "gaps": gaps}, summary


def _build_supplement_tasks(deleted: list[dict], gaps: list[str]) -> list[dict]:
    """把补充工作拆成可并行的任务：被删用例按模块分组各一任务，遗漏场景单独一任务。
    返回 [{"module": 卡片标题, "deleted": [...], "gaps": [...]}]。"""
    tasks: list[dict] = []
    by_mod: dict[str, list[dict]] = {}
    for c in deleted:
        key = title_prefix(c.get("title", "")) or "其它"
        by_mod.setdefault(key, []).append(c)
    for mod, dels in by_mod.items():
        tasks.append({"module": f"{mod}（补被删场景）", "deleted": dels, "gaps": []})
    if gaps:
        tasks.append({"module": "遗漏场景补充", "deleted": [], "gaps": list(gaps)})
    return tasks


async def _supplement_worker(idx: int, item: dict, emit, system: str,
                             kept: list[dict]) -> tuple[list[dict], dict]:
    """补充单个任务：流式生成新用例（思考流经 emit 下发），解析出用例列表返回。
    kept 用于 prompt 里声明「已有标题勿重复」，跨 agent 的最终去重由上层统一收口。"""
    async def on_reasoning(text: str) -> None:
        if text:
            await emit("thinking", {"text": text})

    parts: list[str] = []
    prompt = _supplement_prompt(kept, item.get("deleted", []), item.get("gaps", []))
    with token_usage.stage(token_usage.STAGE_SUPPLEMENT):
        async for piece in LLMService().generate_stream(system, prompt, on_reasoning=on_reasoning):
            parts.append(piece)
            if piece:
                await emit("chunk", {"text": piece})

    cases = [c for c in parse_cases("".join(parts)) if c.get("title") and not c.get("error")]
    return cases, {"count": len(cases)}


def _apply_review(cases: list[dict], reviews: list[dict]) -> tuple[list[dict], list[dict]]:
    """按评审结论拆分为保留与删除两组。未被提及的用例默认保留。"""
    delete_idx = {
        r.get("index") for r in reviews
        if isinstance(r, dict) and r.get("verdict") == "delete" and isinstance(r.get("index"), int)
    }
    kept = [c for i, c in enumerate(cases) if i not in delete_idx]
    deleted = [c for i, c in enumerate(cases) if i in delete_idx]
    return kept, deleted


# _title_prefix / _title_path / _common_prefix_len / _merge_supplements 已移到
# app/utils/case_grouping.py：本模块顶部 import 了 ChromaStore，测试一 import 就连带
# 拉起 chromadb（约 433 MB），使这段纯字符串逻辑没法在 CI 里轻量测。


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

只输出新增用例的 JSON 数组（不要 markdown 代码块），格式与原用例一致（title/priority/precondition/steps/expected_result/knowledge_refs）。若无需补充则输出 []。

title 的【】前缀要与上面已有用例保持同一套层级路径与粒度：补的场景若属于已有某个功能点，
就复用那个功能点的完整前缀（照抄到最后一级），别只写到页面/区块那一级——前缀决定用例在
最终列表里排到哪儿，粒度不一致就会脱离相关功能点。确实是全新功能点时，再按同样规则下钻。"""
