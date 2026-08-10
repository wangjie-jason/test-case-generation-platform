"""token 用量采集的测试（app/utils/token_usage.py）。

只测采集侧的纯逻辑（contextvars 的采集/隔离、usage 解析、周起始），不碰数据库——
落库与聚合在 `app/services/usage_service.py`，需要 sqlalchemy 与 async session，
而 CI 只装 pytest（避开 chromadb 与 torch），import 到就会 ModuleNotFoundError。
这也是采集逻辑单独放在 utils 的原因，与 v0.23 抽 case_grouping 同一思路。

这里钉住的是三处容易被改坏的语义：
① 没装收集器时必须静默跳过，不能抛异常（llm_service 是通用封装，脚本里直接调它
   不该因为缺少采集上下文就崩）；
② 全零 usage 必须丢弃（服务端上报空壳时记进去只会污染统计）；
③ 并发下各 worker 的 stage 互不串台（这正是选 contextvars 而非全局变量的理由）。
"""
import asyncio
from datetime import datetime

import pytest

from app.utils import token_usage


# ------------------------------------------------------------ record / collector

def test_无收集器时静默跳过不抛异常():
    # 不装 collector 直接 record：不能抛，也不该有任何副作用
    token_usage.record("m", {"total_tokens": 100})


def test_采集单条并带上阶段标注():
    with token_usage.collector() as records:
        with token_usage.stage(token_usage.STAGE_REVIEW):
            token_usage.record("deepseek-v4-pro", {
                "prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500,
            })
    assert records == [{
        "stage": "review", "model": "deepseek-v4-pro",
        "prompt_tokens": 1200, "completion_tokens": 300,
        "reasoning_tokens": 0, "total_tokens": 1500,
    }]


def test_未标注阶段时归入_unknown():
    with token_usage.collector() as records:
        token_usage.record("m", {"total_tokens": 10})
    assert records[0]["stage"] == "unknown"


def test_思考_token_从_completion_tokens_details_取出():
    with token_usage.collector() as records:
        token_usage.record("m", {
            "prompt_tokens": 8000, "completion_tokens": 4000, "total_tokens": 12000,
            "completion_tokens_details": {"reasoning_tokens": 3000},
        })
    assert records[0]["reasoning_tokens"] == 3000
    # 思考 token 已含在 completion 内，不应被重复加进 total
    assert records[0]["total_tokens"] == 12000


def test_缺_total_时用_prompt_加_completion_兜底():
    with token_usage.collector() as records:
        token_usage.record("m", {"prompt_tokens": 100, "completion_tokens": 50})
    assert records[0]["total_tokens"] == 150


@pytest.mark.parametrize("usage", [
    {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    {},
    {"prompt_tokens": None, "completion_tokens": None},
    {"prompt_tokens": "abc"},
    # 负数是明显的脏数据，_as_int 归零后整条应被丢弃
    {"prompt_tokens": -5, "completion_tokens": -1, "total_tokens": -6},
])
def test_全零或非法_usage_一律丢弃(usage):
    with token_usage.collector() as records:
        token_usage.record("m", usage)
    assert records == []


def test_非_dict_的_usage_不入库():
    with token_usage.collector() as records:
        token_usage.record("m", None)
        token_usage.record("m", "oops")
    assert records == []


def test_stage_退出后恢复外层不污染():
    with token_usage.collector() as records:
        with token_usage.stage(token_usage.STAGE_GENERATE):
            with token_usage.stage(token_usage.STAGE_SUPPLEMENT):
                token_usage.record("m", {"total_tokens": 1})
            # 内层退出后应回到 generate，而不是残留 supplement
            token_usage.record("m", {"total_tokens": 2})
    assert [r["stage"] for r in records] == ["supplement", "generate"]


def test_收集器退出后不再采集():
    with token_usage.collector() as records:
        token_usage.record("m", {"total_tokens": 1})
    # 出了 with 就没有 sink 了，这条应被丢掉而不是追加到上面那个列表里
    token_usage.record("m", {"total_tokens": 999})
    assert len(records) == 1


# ------------------------------------------------------------ 并发隔离

def test_并发_worker_的阶段互不串台():
    """create_task 复制创建时的上下文：sink 共享（能收齐），stage 各自独立（不串台）。
    这正是 task_service 在顶层装一次 collector 就能覆盖全部并发 worker 的依据。"""
    async def worker(name: str, delay: float) -> None:
        with token_usage.stage(name):
            # 故意交错 await，若 stage 是全局变量这里必然互相覆盖
            await asyncio.sleep(delay)
            token_usage.record("m", {"total_tokens": 1})

    async def main() -> list[dict]:
        with token_usage.collector() as records:
            await asyncio.gather(
                worker(token_usage.STAGE_GENERATE, 0.02),
                worker(token_usage.STAGE_REVIEW, 0.01),
                worker(token_usage.STAGE_SUPPLEMENT, 0.0),
            )
            return list(records)

    records = asyncio.run(main())
    assert sorted(r["stage"] for r in records) == ["generate", "review", "supplement"]


# ------------------------------------------------------------ week_start

@pytest.mark.parametrize("now, expected", [
    # 周一当天 → 当天 00:00
    (datetime(2026, 8, 10, 15, 42, 7), datetime(2026, 8, 10, 0, 0, 0)),
    # 周日 → 回退到本周一（周日属于「本周」，不是下周）
    (datetime(2026, 8, 16, 23, 59, 59), datetime(2026, 8, 10, 0, 0, 0)),
    # 跨月边界
    (datetime(2026, 9, 2, 8, 0, 0), datetime(2026, 8, 31, 0, 0, 0)),
])
def test_week_start_取周一零点(now, expected):
    assert token_usage.week_start(now) == expected


def test_所有阶段常量都有中文标签():
    """新增阶段时若忘了补 STAGE_LABELS，看板会露出裸的英文 stage 名。"""
    stages = [
        token_usage.STAGE_CLARIFY, token_usage.STAGE_MODULE_SPLIT,
        token_usage.STAGE_GENERATE, token_usage.STAGE_REVIEW,
        token_usage.STAGE_SUPPLEMENT,
    ]
    for s in stages:
        assert s in token_usage.STAGE_LABELS
