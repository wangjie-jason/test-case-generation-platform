import asyncio
import json
import logging
import re
import time
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.llm_service import LLMService
from app.services.prompt_service import PromptService
from app.services.retrieval_service import RetrievalService
from app.services.validation_service import ValidationService
from app.utils.case_grouping import merge_supplements, title_path, title_prefix
from app.utils.case_ordering import order_cases
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
            requirement_text=requirement_text, field_dicts=retrieval["field_dicts"],
            business_rules=retrieval["business_rules"], state_machines=retrieval["state_machines"],
            term_mappings=retrieval["term_mappings"], defect_chunks=retrieval.get("defect_chunks"),
            prd_chunks=retrieval.get("prd_chunks"), historical_cases=historical_cases,
        )
        with token_usage.stage(token_usage.STAGE_CLARIFY):
            return await LLMService().generate(system_content, user_content)

    @staticmethod
    async def generate_stream(db: AsyncSession, requirement_text: str, kb_ids: list[str] | None = None) -> AsyncGenerator[dict, None]:
        # 记录整体开始时间，complete 事件里回传总耗时（秒）。
        started_at = time.monotonic()
        yield {"type": "progress", "stage": "retrieving", "message": "正在检索知识库..."}
        retrieval = await RetrievalService.retrieve(db, requirement_text, kb_ids=kb_ids)
        historical_cases = await _get_historical_cases(requirement_text, retrieval["query_keywords"], kb_ids)
        kc = {"field_dicts_count": len(retrieval["field_dicts"]), "business_rules_count": len(retrieval["business_rules"]), "state_machines_count": len(retrieval["state_machines"]), "term_mappings_count": len(retrieval["term_mappings"]), "prd_chunks_count": len(retrieval.get("prd_chunks", [])), "defect_chunks_count": len(retrieval.get("defect_chunks", [])), "historical_cases_count": len(historical_cases)}
        yield {"type": "progress", "stage": "constructing", "message": f"检索到 {sum(kc.values())} 条相关知识"}

        # 检索一结束就把命中的知识明细推给前端，避免等到 complete 才显示（生成/评审/补充耗时较长）。
        # complete 事件里同样带这两个字段，作为断线重连时的兜底，前端幂等赋值。
        km = _knowledge_matches(retrieval, historical_cases)
        yield {"type": "knowledge", "knowledge_used": kc, "knowledge_matches": km}

        # 构造基础 system_content（含知识库上下文），后续所有 LLM 调用复用此 system。
        base_system, _ = PromptService.build(
            requirement_text=requirement_text, field_dicts=retrieval["field_dicts"],
            business_rules=retrieval["business_rules"], state_machines=retrieval["state_machines"],
            term_mappings=retrieval["term_mappings"], defect_chunks=retrieval.get("defect_chunks"),
            prd_chunks=retrieval.get("prd_chunks"), historical_cases=historical_cases,
        )
        llm = LLMService()

        # ── 阶段1：模块拆分（可选） ──
        # 仅在 LLM_ENABLE_MODULE_SPLIT 开启、且需求文本足够长时才抽取模块清单。
        # 小需求（< LLM_MODULE_SPLIT_MIN_CHARS）跳过：单批生成本就撑不满 max_tokens，
        # 抽模块只会白花一次 LLM 调用；且续写式兜底始终生效，跳过不影响防截断。
        modules = None
        if settings.LLM_ENABLE_MODULE_SPLIT and len(requirement_text) >= settings.LLM_MODULE_SPLIT_MIN_CHARS:
            yield {"type": "progress", "stage": "splitting", "message": "正在分析模块结构..."}
            modules = await _extract_modules(llm, requirement_text, retrieval.get("prd_chunks"))
            if not modules or len(modules) <= 1:
                modules = None  # 一个模块或没有，退化为单批

        # ── 阶段2：逐个模块生成（每批内部套续写兜底） ──
        all_cases: list[dict] = []
        # 跨批共用 title 列表，用于续写时防重复。
        all_titles: list[str] = []

        if modules:
            total = len(modules)
            # 把拆分出的模块清单推给前端，让用户看到「本次拆成了哪些模块」，
            # 而不是只显示"正在分析模块结构..."后就闷头生成（此前无从得知拆了什么）。
            yield {"type": "modules", "modules": modules}
            yield {"type": "progress", "stage": "generating",
                   "message": f"已拆分为 {total} 个模块，开始并行生成：{('、'.join(modules))[:120]}"}
            # 模块并行生成：受 LLM_MODULE_CONCURRENCY 并发上限约束，并按
            # LLM_MODULE_STAGGER_DELAY 错峰启动，避免瞬间大量请求撞到套餐限流。
            # 每个模块用独立的 LLMService 实例——因为续写兜底依赖实例上的
            # last_finish_reason 状态，共享一个实例会互相覆盖导致判断错乱。
            # 跨模块的 title 去重不再实时共享（并发下无法安全共享可变列表），
            # 改由全部完成后的 _dedup_by_title 统一按归一化 title 精确去重。
            sem = asyncio.Semaphore(max(1, settings.LLM_MODULE_CONCURRENCY))
            stagger = max(0.0, settings.LLM_MODULE_STAGGER_DELAY)
            # 汇流队列：各模块并发跑，把带 module_index 的事件（开始/流式chunk/完成/失败）
            # 推入这个队列，由主生成器单点取出并 yield。这样多 agent 的实时流不会在
            # yield 层交错错乱，且每个事件都带模块下标，前端可按 agent 分区展示各自的流。
            event_q: asyncio.Queue = asyncio.Queue()

            async def _run_module(idx: int, module: str) -> None:
                # 错峰：第 idx 个模块延迟 idx*stagger 秒再启动，把并发启动的
                # 请求突刺摊平成平滑曲线，进一步降低 429 概率。
                if stagger and idx:
                    await asyncio.sleep(idx * stagger)
                async with sem:
                    # 该模块真正开始生成的时间：不含错峰/排队等待，只计入 LLM 生成本身。
                    mod_start = time.monotonic()
                    await event_q.put({"type": "module_start", "index": idx, "module": module})

                    async def _on_chunk(text: str) -> None:
                        # 该模块的实时正文流：带 index，前端归档到对应 agent 卡片。
                        await event_q.put({"type": "module_chunk", "index": idx, "text": text})

                    async def _on_reasoning(text: str) -> None:
                        # 该模块的思考流：同样推给前端，但用独立事件类型，
                        # 前端在思考阶段展示 🤔 思考中，避免干等"等待模型输出"。
                        await event_q.put({"type": "module_thinking", "index": idx, "text": text})

                    try:
                        batch = await _generate_one_batch(
                            LLMService(), base_system, requirement_text, retrieval, historical_cases,
                            module_focus=module, existing_titles=[], on_chunk=_on_chunk,
                            on_reasoning=_on_reasoning,
                        )
                    except Exception:
                        logger.exception("模块[%s]并行生成失败", module)
                        await event_q.put({"type": "module_failed", "index": idx, "module": module,
                                           "elapsed": round(time.monotonic() - mod_start, 1)})
                        return
                    await event_q.put({"type": "module_done", "index": idx, "module": module, "cases": batch,
                                       "elapsed": round(time.monotonic() - mod_start, 1)})

            tasks = [asyncio.create_task(_run_module(i, m)) for i, m in enumerate(modules)]

            # 单点消费队列并 yield，直到所有模块都产出了终态（done/failed）。
            # 各模块并发完成、到达时序不定，若按完成顺序直接 extend，模块间顺序就与切割
            # 时的 modules 列表错位。这里按模块下标（即 modules 的下标）暂存各自 batch，
            # 全部结束后再按 0..total-1 顺序拼接，保证最终用例严格按切割模块顺序排列。
            batches_by_index: dict[int, list[dict]] = {}
            done_count = 0
            while done_count < total:
                ev = await event_q.get()
                etype = ev["type"]
                if etype == "module_start":
                    yield ev
                elif etype in ("module_chunk", "module_thinking"):
                    yield ev
                elif etype == "module_failed":
                    done_count += 1
                    yield {"type": "module_failed", "index": ev["index"], "module": ev["module"],
                           "elapsed": ev.get("elapsed")}
                    yield {"type": "progress", "stage": "generating",
                           "message": f"模块生成进度 {done_count}/{total}（模块「{ev['module']}」失败已跳过）"}
                elif etype == "module_done":
                    done_count += 1
                    batch = ev.get("cases") or []
                    if batch:
                        logger.info("模块[%s]生成 %d 条用例", ev["module"], len(batch))
                        batches_by_index[ev["index"]] = batch
                    # 把该模块解析出的用例随完成事件下发，前端用它把卡片从「流式文本」
                    # 切换为解析好的用例列表。elapsed 为该模块生成耗时（秒）。
                    yield {"type": "module_done", "index": ev["index"], "module": ev["module"], "cases": batch,
                           "elapsed": ev.get("elapsed")}
                    yield {"type": "progress", "stage": "generating",
                           "message": f"模块生成进度 {done_count}/{total}：{ev['module']}"}
            # 按模块下标（modules 的顺序）拼接，抹平并发完成时序带来的乱序。
            for idx in range(total):
                all_cases.extend(batches_by_index.get(idx, []))
            # 兜底：确保所有任务已结束（正常情况下 done_count 达标时它们都已 return）。
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            # 无模块分批：单批生成 + 续写兜底
            yield {"type": "progress", "stage": "generating", "message": "AI正在生成..."}
            _, user_content = PromptService.build(
                requirement_text=requirement_text, field_dicts=retrieval["field_dicts"],
                business_rules=retrieval["business_rules"], state_machines=retrieval["state_machines"],
                term_mappings=retrieval["term_mappings"], defect_chunks=retrieval.get("defect_chunks"),
                prd_chunks=retrieval.get("prd_chunks"), historical_cases=historical_cases,
            )
            all_cases = await _generate_one_batch(
                llm, base_system, requirement_text, retrieval, historical_cases,
                module_focus=None, existing_titles=all_titles,
                user_content=user_content,
            )

        # ── 跨批去重（按 title 归一化后精确匹配） ──
        if len(all_cases) > 1:
            deduped = _dedup_by_title(all_cases)
            if len(deduped) < len(all_cases):
                logger.info("去重合并：%d → %d 条", len(all_cases), len(deduped))
            all_cases = deduped

        # 没有任何有效用例（解析失败 / 模型合法空结果 / 只思考未输出）：这不是"成功生成 0 条"，
        # 而是一次失败。作为 error 事件抛给前端并 return——既让前端显示明确原因（而非"成功，共 1 条"），
        # 又因为不 emit complete，task_service 不会把 error 占位用例落库污染历史。
        if not _has_valid_cases(all_cases):
            reason = next((c.get("error") for c in all_cases if c.get("error")), None) \
                or "未生成任何有效用例，请补充更明确的需求描述后重试"
            yield {"type": "error", "message": reason}
            return
        yield {"type": "progress", "stage": "validating", "message": "正在校验..."}
        warnings = await ValidationService.validate_cases(db, all_cases)

        # 评审：以测试专家身份逐条判定保留/删除，不改写已生成的用例。
        # 按【模块】把用例分组，每组一个独立评审 agent 并行跑（与生成阶段同一套
        # Semaphore 错峰 + 事件队列机制），每个 agent 一张卡片实时流式展示评审过程，
        # 用户能看到「AI 正在保留/删除哪条、理由是什么」，而不是干等一句静态提示。
        if _has_valid_cases(all_cases):
            yield {"type": "progress", "stage": "reviewing", "message": "测试专家正在分模块并行评审用例..."}
            groups = _group_by_module(all_cases)
            warnings_by_global = {
                w["case_index"]: w for w in warnings if isinstance(w.get("case_index"), int)
            }
            review = {"reviews": [], "gaps": []}
            async for ev in _parallel_agents(
                groups,
                lambda i, g, emit: _review_worker(i, g, emit, base_system, warnings_by_global),
                phase="review",
            ):
                if ev["type"] == "_results":
                    for r in ev["results"]:
                        if isinstance(r, dict):
                            review["reviews"].extend(r.get("reviews", []))
                            review["gaps"].extend(r.get("gaps", []))
                else:
                    yield ev

            kept, deleted = _apply_review(all_cases, review["reviews"])
            if _has_valid_cases(kept):
                all_cases = kept
            else:
                deleted = []  # 评审把用例全删了，判定不可信，全部保留
            gaps = review["gaps"]
            if deleted:
                yield {"type": "progress", "stage": "reviewing", "message": f"评审删除 {len(deleted)} 条问题用例，保留 {len(all_cases)} 条"}

            # 补充：把被删场景按模块分组、遗漏场景单独一组，每组一个补充 agent 并行生成，
            # 各自一张卡片实时流式展示。生成后跨 agent + 与保留用例统一按 title 去重再合并。
            if deleted or gaps:
                yield {"type": "progress", "stage": "supplementing", "message": "正在分模块并行补充遗漏场景的用例..."}
                supp_tasks = _build_supplement_tasks(deleted, gaps)
                collected: list[dict] = []
                async for ev in _parallel_agents(
                    supp_tasks,
                    lambda i, it, emit: _supplement_worker(i, it, emit, base_system, all_cases),
                    phase="supplement",
                ):
                    if ev["type"] == "_results":
                        for r in ev["results"]:
                            if isinstance(r, list):
                                collected.extend(r)
                    else:
                        yield ev
                # 跨 agent + 与已保留用例统一去重（并行下无法实时共享 title，完成后统一收口）。
                existing = {_title_key(c.get("title", "")) for c in all_cases}
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
                    all_cases = merge_supplements(all_cases, supplements)
                    yield {"type": "progress", "stage": "supplementing", "message": f"补充 {len(supplements)} 条用例，共 {len(all_cases)} 条"}
            # 收口排序：让补充用例挨到相关功能点旁边。放在这里有两个原因——
            # ① 必须在 validate_cases 之前：告警按下标引用用例，排完再校验才不会错位；
            # ② 必须在补充合并之后：补充用例正是要归位的对象。
            # 只挪补充用例（is_movable），原有用例位置一律不动——路径层与功能点层都受此
            # 约束（只在功能点层拦不住：路径排序自己就会把交错的同路径用例并段）。
            # LLM 一次产出的用例本就按功能点聚好（实测 350 个子功能路径仅 6 个被拆段），
            # 而功能点判定靠字面共同前缀这一启发式，动原有用例收益小、误吸附风险大。
            # 顶层模块顺序不受影响：all_cases 已按切割模块下标拼接，order_cases 只识别
            # 块边界、不重排块序。
            all_cases = order_cases(all_cases, lambda c: c.get("title") or "",
                                    lambda c: c.get("origin") == "supplement")
            warnings = await ValidationService.validate_cases(db, all_cases)

        yield {"type": "complete", "cases": all_cases, "knowledge_used": kc, "knowledge_matches": km,
               "validation_warnings": warnings, "elapsed": round(time.monotonic() - started_at, 1)}


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


async def _extract_modules(llm, requirement_text: str, prd_chunks: list[dict] | None) -> list[str] | None:
    """阶段1：让 LLM 抽取【模块清单】。失败或无法确认时返回 None（上层退化为单批）。

    模块拆分是「优化层」，其失败绝不能阻断生成——抽取异常、解析失败、模型判定
    覆盖不全（covers_all=false）时，一律返回 None 回退到单批续写式，只打告警日志。
    """
    try:
        system, user = PromptService.build_module_split(requirement_text, prd_chunks)
        with token_usage.stage(token_usage.STAGE_MODULE_SPLIT):
            raw = await llm.generate(system, user)
        parsed = _parse_json_object(raw, require_key="modules")
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


async def _generate_one_batch(
    llm, base_system: str, requirement_text: str, retrieval: dict,
    historical_cases: list[dict], module_focus: str | None,
    existing_titles: list[str], user_content: str | None = None,
    on_chunk=None, on_reasoning=None,
) -> list[dict]:
    """生成一批用例，内含「续写式」兜底：撞满 max_tokens 就带着已有 title 续写，
    循环到 finish_reason != length 或达到 LLM_MAX_CONTINUATIONS 上限。

    existing_titles 会被就地追加本批新生成的 title（跨批共享，供后续批次/续写防重复）。
    module_focus 非空时按该模块聚焦生成；user_content 显式传入时优先使用（单批路径复用）。
    on_chunk 非空时，每收到一段流式文本就以其为参数调用（可为 async），供上层按模块
    实时展示该 agent 的输出流。返回本批解析出的用例列表（可能为空）。
    """
    if user_content is None:
        _, user_content = PromptService.build(
            requirement_text=requirement_text, field_dicts=retrieval["field_dicts"],
            business_rules=retrieval["business_rules"], state_machines=retrieval["state_machines"],
            term_mappings=retrieval["term_mappings"], defect_chunks=retrieval.get("defect_chunks"),
            prd_chunks=retrieval.get("prd_chunks"), historical_cases=historical_cases,
            module_focus=module_focus,
        )

    batch_cases: list[dict] = []
    cur_user = user_content
    for attempt in range(settings.LLM_MAX_CONTINUATIONS + 1):
        # 流式收取：边收边把原始文本通过 on_chunk 推给上层展示，同时累积成整段
        # 供后续 _parse_cases 解析。相比一次性 generate()，用户能看到 agent 实时吐字。
        parts: list[str] = []
        with token_usage.stage(token_usage.STAGE_GENERATE):
            async for piece in llm.generate_stream(base_system, cur_user, on_reasoning=on_reasoning):
                parts.append(piece)
                if on_chunk is not None and piece:
                    res = on_chunk(piece)
                    if asyncio.iscoroutine(res):
                        await res
        raw = "".join(parts)
        cases = [c for c in _parse_cases(raw) if c.get("title") and not c.get("error")]
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


def _group_by_module(cases: list[dict]) -> list[dict]:
    """按标题【】里的**前两级**模块路径把用例分组，保留每条用例的全局下标（供评审结论
    映射回整批）。无模块前缀的归入「其它」。
    返回 [{"module": 名, "items": [(global_idx, case), ...]}]。

    取两级而非只取顶层：顶层前缀只是【】里 - 之前的第一段，实测 1097 条的批次里「PC」
    一个模块就独占 629 条，一次性塞进评审 prompt 会撞满 max_tokens，截断后整组判定
    静默丢失。取两级后最大组降到 107 条，且分组边界跟着内容自己的层级走——顶层分组
    再按条数切出的 `PC (2/4)` 既看不出在评审什么，边界也全落在二级模块中间，换个
    PRD（全部功能挂在同一顶层模块下）就完全退化成纯数字切块。
    判重能力两种分法是平局：实测同二级模块内被切开的疑似重复对与跨二级模块本可判出
    的对数各 1，净效应为零，故不作为取舍依据。

    LLM_REVIEW_BATCH_SIZE 降级为兜底：仅当单个二级模块仍然超限时才按条数均分切块。
    切块后卡片标题带 (n/N) 后缀，便于在前端区分同一模块的多个评审 agent。
    """
    groups: dict[str, list[tuple[int, dict]]] = {}
    for i, c in enumerate(cases):
        path = title_path(c.get("title", ""))
        key = "-".join(path[:2]) if path else "其它"
        groups.setdefault(key, []).append((i, c))
    cap = max(1, settings.LLM_REVIEW_BATCH_SIZE)
    out: list[dict] = []
    for key, items in groups.items():
        if len(items) <= cap:
            out.append({"module": key, "items": items})
            continue
        # 均分而非按 cap 贪心切：500 条按 cap=200 贪心会切出 200/200/100，最后那块
        # 明显偏小却同样白占一次调用和一张卡片；先算块数再均分得到 167/167/166。
        n_chunks = -(-len(items) // cap)
        size = -(-len(items) // n_chunks)
        chunks = [items[s:s + size] for s in range(0, len(items), size)]
        for n, chunk in enumerate(chunks, 1):
            out.append({"module": f"{key} ({n}/{len(chunks)})", "items": chunk})
    return out


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
    parsed = _parse_json_object(raw, require_key="reviews")
    raw_reviews = parsed.get("reviews") if isinstance(parsed, dict) else None
    if not isinstance(raw_reviews, list):
        raw_reviews = _salvage_reviews(raw)
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

    cases = [c for c in _parse_cases("".join(parts)) if c.get("title") and not c.get("error")]
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


def _parse_json_object(raw: str, require_key: str | None = None) -> dict | None:
    """从 LLM 输出中解析出一个 JSON 对象（容忍 markdown 代码块包裹）。

    require_key：调用方期望的顶层键，给了就只接受含该键的对象。末端的 raw_decode 兜底会
    从每一个 `{` 起试解，响应被截断（顶层对象未闭合）时极易解出**内层**的某个子对象并
    当成顶层返回——评审就踩过这个坑：截断后它返回了第一条 verdict 对象，调用方
    .get("reviews") 拿到空列表，整组判定静默归零、一条都没删。
    """
    def usable(obj) -> bool:
        return isinstance(obj, dict) and (require_key is None or require_key in obj)

    try:
        parsed = json.loads(raw)
        if usable(parsed):
            return parsed
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m:
        try:
            parsed = json.loads(m.group(1))
            if usable(parsed):
                return parsed
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    start = raw.find("{")
    while start != -1:
        try:
            parsed, _ = decoder.raw_decode(raw[start:])
            if usable(parsed):
                return parsed
        except json.JSONDecodeError:
            pass
        start = raw.find("{", start + 1)
    return None


def _salvage_reviews(raw: str) -> list[dict]:
    """从残缺的评审输出里逐个抓完整的判定对象（同 _salvage_truncated_cases 的手法）。

    评审撞满 max_tokens 时顶层 JSON 不闭合，整体解析必然失败，但每条已吐完的判定本身
    还是合法 JSON，raw_decode 可以从任意位置起解一个对象。判据用 index —— 判定条目的
    必备字段。这样至少保住截断前已经判完的那部分，而不是整组归零。
    """
    decoder = json.JSONDecoder()
    out: list[dict] = []
    i = raw.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(raw[i:])
        except json.JSONDecodeError:
            # 当前位置解不出来（比如最后被切断的那条）—— 跳到下一个 `{` 重试。
            i = raw.find("{", i + 1)
            continue
        if isinstance(obj, dict) and "index" in obj:
            out.append(obj)
        # 从这个对象结束的位置继续找，跳过内部嵌套避免误抓。
        i = raw.find("{", i + end)
    return out


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
    parsed = _parse_json_object(raw, require_key="cases")
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
