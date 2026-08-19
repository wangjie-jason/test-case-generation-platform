"""薄壳：把拆分后的生成流水线对外仍然以 generator_service 的名字暴露。

拆分后的实际逻辑分布在：
- app.services.pipeline             顶层编排（GeneratorService.clarify / generate_stream）
- app.services.pipeline_context     共享上下文与工具（_Context、_get_historical_cases 等）
- app.services.pipeline_generate    阶段①：模块拆分 + 生成
- app.services.pipeline_review      阶段②：自动校验 + 评审
- app.services.pipeline_supplement  阶段③：分模块补充

保留本文件是为了让既有引用（routers/generation.py、task_service.py、测试）不用改 import
路径。测试还会 monkeypatch 本模块上的 LLMService / RetrievalService / ValidationService /
settings / _get_historical_cases，因此这些符号全部重新 export。
"""
from app.config import settings
from app.services.llm_service import LLMService
from app.services.pipeline import GeneratorService
from app.services.pipeline_context import _get_historical_cases
from app.services.pipeline_generate import (
    _extract_modules,
    _generate_by_modules,
    _generate_one_batch,
    _module_worker,
    _stage_generate,
)
from app.services.pipeline_review import (
    _apply_review,
    _group_by_module,
    _review_worker,
    _split_module_group,
    _stage_review,
)
from app.services.pipeline_supplement import (
    _build_supplement_tasks,
    _stage_supplement,
    _supplement_worker,
)
from app.services.retrieval_service import RetrievalService
from app.services.validation_service import ValidationService

__all__ = [
    "GeneratorService",
    "LLMService",
    "RetrievalService",
    "ValidationService",
    "settings",
    "_get_historical_cases",
    "_extract_modules",
    "_generate_by_modules",
    "_generate_one_batch",
    "_module_worker",
    "_stage_generate",
    "_apply_review",
    "_group_by_module",
    "_review_worker",
    "_split_module_group",
    "_stage_review",
    "_build_supplement_tasks",
    "_stage_supplement",
    "_supplement_worker",
]
