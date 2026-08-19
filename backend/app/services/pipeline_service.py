"""生成流水线：检索 → 生成 → 校验+评审 → 补充 → 收口排序。

公开 API：
- GeneratorService.clarify：基于知识库补全（澄清）需求，不生成用例
- GeneratorService.generate_stream：完整流水线，按阶段 yield 事件给前端

流水线由若干 stage 串成，每个 stage 自己 yield 阶段事件、最后用 _results 事件
回传阶段产物。本模块只负责串阶段、转发事件、做阶段间判定，不掺任何阶段内部细节。

实际各阶段逻辑在同目录的 stage 模块里：
- pipeline_deps       外部依赖接缝（LLM/检索/校验的注入点，测试在此换实现）
- pipeline_context_service    共享上下文（_Context、检索、prompt 助手、并发运行器等）
- pipeline_generate_service   阶段①：模块拆分 + 分模块/单批生成 + 跨批去重
- pipeline_review_service     阶段②：自动校验 + 分模块并行评审
- pipeline_supplement_service 阶段③：按模块/遗漏场景并行补充
"""
import time
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import pipeline_context_service
from app.services import pipeline_deps as deps
from app.services.pipeline_context_service import (
    _build_context,
    _has_valid_cases,
    _prompt_kwargs,
)
from app.services.pipeline_generate_service import _stage_generate
from app.services.pipeline_review_service import _stage_review
from app.services.pipeline_supplement_service import _stage_supplement
from app.services.prompt_service import PromptService
from app.utils import token_usage
from app.utils.case_ordering import order_cases


class GeneratorService:

    @staticmethod
    async def clarify(db: AsyncSession, requirement_text: str, kb_ids: list[str] | None = None) -> str:
        """基于知识库补全（澄清）需求：检索 → LLM 补全 → 返回 Markdown 文本。
        不生成测试用例，只产出结构化的完整需求说明。"""
        retrieval = await deps.RetrievalService.retrieve(db, requirement_text, kb_ids=kb_ids)
        # 走模块属性而非 from-import：与 _build_context 保持同一个可替换接缝，否则测试
        # 替掉 pipeline_context_service._get_historical_cases 时只有 generate_stream 生效、
        # clarify 静默用真实实现（拆分前两者同在一个模块，不存在这个缺口）。
        historical_cases = await pipeline_context_service._get_historical_cases(
            requirement_text, retrieval["query_keywords"], kb_ids)
        system_content, user_content = PromptService.build_clarify(
            **_prompt_kwargs(requirement_text, retrieval, historical_cases)
        )
        with token_usage.stage(token_usage.STAGE_CLARIFY):
            return await deps.LLMService().generate(system_content, user_content)

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
        gaps: list[str] = []
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
