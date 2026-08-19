"""补充阶段：把被删场景按模块分组、遗漏场景单独一组并行补充。

外部调用方只需要 _stage_supplement：传进来 _Context、保留用例、被删用例、遗漏场景，
自己 yield 阶段事件，最后用 _results 事件回传合并后的用例列表。
"""
import logging
from typing import AsyncGenerator

from app.services import pipeline_deps as deps
from app.services.pipeline_context_service import (
    _Context,
    _parallel_agents,
    _title_key,
)
from app.utils.case_grouping import merge_supplements, title_prefix
from app.utils.llm_parsing import parse_cases
from app.utils import token_usage

logger = logging.getLogger(__name__)


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
        async for piece in deps.LLMService().generate_stream(system, prompt, on_reasoning=on_reasoning):
            parts.append(piece)
            if piece:
                await emit("chunk", {"text": piece})

    cases = [c for c in parse_cases("".join(parts)) if c.get("title") and not c.get("error")]
    return cases, {"count": len(cases)}


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
