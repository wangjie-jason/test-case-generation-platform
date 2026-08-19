"""生成流水线的共享上下文与工具。

集中放**多个** stage 模块都会用到的小工具：
- _Context：阶段间共享的检索结果与 prompt 上下文 dataclass
- _build_context：跑一次检索 + 历史用例 + 基础 system prompt
- _prompt_kwargs：把检索结果摊平给 PromptService 的入参
- _knowledge_matches / _pick / _clip_value / _clip_text：推给前端的命中知识脱敏
- _get_historical_cases：历史用例的少量检索
- _has_valid_cases：是否有至少一条有效用例
- _title_key / _dedup_by_title：title 归一化与跨批去重
- _parallel_agents：通用「多 agent 并行 + 单点汇流」运行器（生成/评审/补充共用）

判据是「≥2 个 stage 复用」：只服务单一阶段的东西一律放回该阶段自己的模块，
免得这里退化成 utils 垃圾桶——评审 prompt（_review_prompt / _case_brief）因此已挪回
pipeline_review_service，与 pipeline_supplement_service 自带 _supplement_prompt 的摆法对齐。
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services import pipeline_deps as deps
from app.services.prompt_service import PromptService
from app.vectorstore.chroma_client import ChromaStore

logger = logging.getLogger(__name__)


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
    retrieval = await deps.RetrievalService.retrieve(db, requirement_text, kb_ids=kb_ids)
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


def _clip_value(value: Any) -> Any:
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


def _title_key(title: str) -> str:
    """title 归一化：去首尾空白 + 全角转半角 + 内部空白折叠，用于跨批精确去重。"""
    if not title:
        return ""
    # 全角空格/标点常见变体归一（只处理空白，避免误伤业务语义）
    t = title.replace("\u3000", " ").strip()
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
