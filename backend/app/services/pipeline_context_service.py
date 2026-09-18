"""生成流水线的共享上下文与工具。

集中放**多个** stage 模块都会用到的小工具：
- _Context：阶段间共享的检索结果与 prompt 上下文 dataclass
- _prompt_kwargs：把检索结果摊平给 PromptService 的入参（clarify 与生成 stage 共用）
- _has_valid_cases：是否有至少一条有效用例（编排器与评审 stage 共用）
- _title_key：title 归一化（生成/补充 stage 的去重共用）
- _parallel_agents：通用「多 agent 并行 + 单点汇流」运行器（生成/评审/补充共用）

判据是「≥2 个 stage 复用」：只服务编排器的 _build_context/_get_historical_cases 与命中
知识脱敏助手放在 pipeline_service，单阶段专用的 _dedup_by_title 在 pipeline_generate_service，
免得这里退化成 utils 垃圾桶——评审 prompt（_review_prompt / _case_brief）此前也据此挪回
pipeline_review_service，与 pipeline_supplement_service 自带 _supplement_prompt 的摆法对齐。
"""
import asyncio
import logging
import time
from dataclasses import dataclass

from app.config import settings

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


def _has_valid_cases(cases: list[dict]) -> bool:
    return any(case.get("title") and not case.get("error") for case in cases)


def _title_key(title: str) -> str:
    """title 归一化：去首尾空白 + 全角转半角 + 内部空白折叠，用于跨批精确去重。"""
    if not title:
        return ""
    # 全角空格/标点常见变体归一（只处理空白，避免误伤业务语义）
    t = title.replace("\u3000", " ").strip()
    return " ".join(t.split())


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
