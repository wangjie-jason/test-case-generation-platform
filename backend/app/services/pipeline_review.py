"""评审阶段：自动校验 + 按模块分组并行评审，最后合并保/删判定。

外部调用方只需要 _stage_review：传进来 _Context 与生成阶段的用例列表，
自己 yield 阶段事件，最后用 _results 事件回传 (保留的用例, 被删用例, 遗漏场景)。
"""
import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
import app.services.generator_service as _gs  # late-bound: tests monkeypatch gs.LLMService / gs.ValidationService
from app.services.pipeline_context import (
    _Context,
    _has_valid_cases,
    _parallel_agents,
    _review_prompt,
)
from app.utils.case_grouping import title_path
from app.utils.llm_parsing import parse_json_object, salvage_reviews
from app.utils import token_usage

logger = logging.getLogger(__name__)


async def _stage_review(db: AsyncSession, ctx: _Context,
                        cases: list[dict]) -> AsyncGenerator[dict, None]:
    """阶段②：自动校验 + 分模块并行评审。_results 回传 (保留的用例, 被删用例, 遗漏场景)。

    评审以测试专家身份逐条判定保留/删除，不改写已生成的用例。按【模块】把用例分组，每组
    一个独立评审 agent 并行跑，每个 agent 一张卡片实时流式展示评审过程，用户能看到
    「AI 正在保留/删除哪条、理由是什么」，而不是干等一句静态提示。

    校验必须在这里跑（评审之前）：告警按用例下标引用，要与评审分组用的是同一份列表下标。
    """
    yield {"type": "progress", "stage": "validating", "message": "正在校验..."}
    warnings = await _gs.ValidationService.validate_cases(db, cases)

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
    llm = _gs.LLMService()
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


def _apply_review(cases: list[dict], reviews: list[dict]) -> tuple[list[dict], list[dict]]:
    """按评审结论拆分为保留与删除两组。未被提及的用例默认保留。"""
    delete_idx = {
        r.get("index") for r in reviews
        if isinstance(r, dict) and r.get("verdict") == "delete" and isinstance(r.get("index"), int)
    }
    kept = [c for i, c in enumerate(cases) if i not in delete_idx]
    deleted = [c for i, c in enumerate(cases) if i in delete_idx]
    return kept, deleted
