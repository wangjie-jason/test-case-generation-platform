"""薄壳：把拆分后的生成流水线对外仍然以 generator_service 的名字暴露。

拆分后的实际逻辑分布在（与同目录其它模块一样带 _service 后缀）：
- app.services.pipeline_service             顶层编排（GeneratorService.clarify / generate_stream）
- app.services.pipeline_deps                外部依赖接缝（LLM/检索/校验的注入点）
- app.services.pipeline_context_service     跨阶段共享的上下文与工具（_Context、_parallel_agents 等）
- app.services.pipeline_generate_service    阶段①：模块拆分 + 生成
- app.services.pipeline_review_service      阶段②：自动校验 + 评审
- app.services.pipeline_supplement_service  阶段③：分模块补充

保留本文件是为了让既有引用（routers/generation.py、task_service.py）不用改 import 路径。
本文件是**单向** re-export，不被任何 pipeline_* 模块反向 import——曾经反过来（stage 模块
`import generator_service as _gs` 取 LLMService）导致 5 个 pipeline 模块全都无法独立 import，
接缝已下沉到 pipeline_deps，详见该模块 docstring。

只转出真正有外部消费方的名字。此前 __all__ 里还列了 13 个 stage 私有函数
（_stage_generate / _group_by_module / _apply_review 等），运行时与测试皆零引用——
私有实现不该因为"顺手"就进 __all__，各 stage 模块内部按 _ 前缀自用即可。

要在测试里替换外部依赖，请 patch **pipeline_deps**（`monkeypatch.setattr(pipeline_deps,
"LLMService", FakeLLM)`）而不是本模块——本模块的 LLMService 等只是名字转出，替这里不生效。
settings 例外：全局同一个实例，patch 其属性在任何模块都生效。
"""
from app.config import settings
from app.services.llm_service import LLMService
from app.services.pipeline_service import GeneratorService
from app.services.retrieval_service import RetrievalService
from app.services.validation_service import ValidationService

__all__ = [
    "GeneratorService",
    "LLMService",
    "RetrievalService",
    "ValidationService",
    "settings",
]
