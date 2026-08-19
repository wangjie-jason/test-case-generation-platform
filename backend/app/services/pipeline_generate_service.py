"""生成阶段：模块拆分（可选）→ 单批/分模块并行生成 → 跨批去重。

外部调用方只需要 _stage_generate：传进来 _Context，自己 yield 阶段事件，
最后用 _results 事件回传最终生成的用例列表。
"""
import asyncio
import logging
from typing import AsyncGenerator

from app.config import settings
from app.services import pipeline_deps as deps
from app.services.prompt_service import PromptService
from app.services.pipeline_context_service import (
    _Context,
    _dedup_by_title,
    _parallel_agents,
    _prompt_kwargs,
    _title_key,
)
from app.utils.llm_parsing import parse_cases, parse_json_object
from app.utils import token_usage

logger = logging.getLogger(__name__)


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
    llm = deps.LLMService()
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

    batch = await _generate_one_batch(deps.LLMService(), ctx, module_focus=module, existing_titles=[],
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

    module_focus 非空时按该模块聚焦生成，为 None 则是不分模块的单批。
    existing_titles 会被**就地追加**本批新生成的 title（供续写防重复），调用方传进来的
    列表会被改动——续写轮依赖这份累积状态，不是可省略的实现细节。
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
