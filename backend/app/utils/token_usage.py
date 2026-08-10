"""LLM token 用量的**采集**逻辑（纯 Python，不依赖 sqlalchemy）。

为什么与 `services/usage_service.py` 分开：CI 只装 pytest，不装 requirements.txt
（避开 chromadb 约 433 MB 与 sentence-transformers 带的 torch）。usage_service 需要
sqlalchemy 做聚合查询，测试一 import 就 ModuleNotFoundError。而采集本身只是
contextvars + dict 处理，与数据库无关——照 v0.23 抽 `case_grouping` 的先例拆出来，
测试只 import 本模块即可轻量跑。

采集为什么走 contextvars 而不是改调用签名：`LLMService()` 在 5 个地方各自 new
（clarify / 模块拆分 / 生成 / 评审 / 补充），其中三处还跑在 `asyncio.create_task`
起的并发 worker 里。要把「这次消耗归属于哪个阶段」层层透传，就得改遍
generator_service 里所有 worker 的签名和 `_parallel_agents` 的协议——收益全无。
contextvars 天然满足这里的需求：`create_task` 会复制创建时的上下文，因此
① 在 task_service 顶层装一次收集器，所有并发 worker 都能写进同一个 sink；
② 每个 worker 内部 `stage()` 只影响自己的上下文副本，并发下不会互相串台。
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Iterator

# 阶段标识。与生成流程里 progress 事件的 stage 命名保持一致，便于前端复用文案。
STAGE_CLARIFY = "clarify"
STAGE_MODULE_SPLIT = "module_split"
STAGE_GENERATE = "generate"
STAGE_REVIEW = "review"
STAGE_SUPPLEMENT = "supplement"

STAGE_LABELS = {
    STAGE_CLARIFY: "需求补全",
    STAGE_MODULE_SPLIT: "模块拆分",
    STAGE_GENERATE: "用例生成",
    STAGE_REVIEW: "评审",
    STAGE_SUPPLEMENT: "补充",
    "unknown": "未标注",
}

_sink: ContextVar[list[dict] | None] = ContextVar("llm_usage_sink", default=None)
_stage: ContextVar[str] = ContextVar("llm_usage_stage", default="unknown")


@contextmanager
def collector() -> Iterator[list[dict]]:
    """在当前上下文装一个用量收集器，yield 出的列表会收到本次调用链的所有流水。

    必须在起并发 worker **之前**装好：`create_task` 复制的是创建那一刻的上下文，
    装晚了 worker 就看不到这个 sink，用量会静默丢失。
    """
    records: list[dict] = []
    token = _sink.set(records)
    try:
        yield records
    finally:
        _sink.reset(token)


@contextmanager
def stage(name: str) -> Iterator[None]:
    """标注接下来的 LLM 调用属于哪个阶段。用 reset 而非直接 set，避免退出后污染外层。"""
    token = _stage.set(name)
    try:
        yield
    finally:
        _stage.reset(token)


def record(model: str, usage: dict) -> None:
    """把服务端上报的一段 usage 记进当前 sink。没装收集器时静默跳过。

    静默跳过是有意的：llm_service 是通用封装，脚本或测试里直接调它不该因为
    没有采集上下文就报错。代价是漏采，但漏采只影响统计，不影响生成本身。
    """
    sink = _sink.get()
    if sink is None:
        return
    if not isinstance(usage, dict):
        return

    prompt = _as_int(usage.get("prompt_tokens"))
    completion = _as_int(usage.get("completion_tokens"))
    total = _as_int(usage.get("total_tokens")) or (prompt + completion)
    # 推理 token 在 OpenAI / DeepSeek 兼容协议里放在 completion_tokens_details 下。
    # 它已被计入 completion_tokens，这里单独取出只为回答「思考占多少」。
    details = usage.get("completion_tokens_details")
    reasoning = _as_int(details.get("reasoning_tokens")) if isinstance(details, dict) else 0

    # 三个计数全为 0 说明服务端没真正上报（或上报了空壳），记下来只会污染统计。
    if not (prompt or completion or total):
        return

    sink.append({
        "stage": _stage.get(),
        "model": model,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "total_tokens": total,
    })


def _as_int(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def day_start(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def week_start(dt: datetime) -> datetime:
    """本周起始（周一 00:00）。库里存的是 naive 的 Asia/Shanghai 时间，直接比较即可。"""
    return day_start(dt) - timedelta(days=dt.weekday())
