"""生成流水线的外部依赖接缝（依赖注入点）。

各 stage 模块一律通过 `deps.LLMService()` / `deps.RetrievalService` / `deps.ValidationService`
调用外部服务，而不是直接 import 它们——**属性查找发生在调用时**，替换实现无需触碰业务代码。

本模块只 import 叶子服务，**绝不 import 任何 pipeline_* 模块**：这条单向约束是它存在的
另一半理由。此前这个接缝挂在 `generator_service` 上（stage 模块反过来
`import app.services.generator_service as _gs`），与 `generator_service` 对 stage 模块的
正向 import 构成环——实测 5 个 pipeline 模块全都无法独立 import
（`ImportError: cannot import name '_stage_review' from partially initialized module`），
只因所有运行时入口恰好先 import `generator_service` 才没暴雷。把接缝下沉到这个叶子模块后
依赖变成单向：
generator_service → pipeline_service → pipeline_*_service → pipeline_deps → 叶子服务。

注意 `settings` 不在这里：各模块直接 `from app.config import settings` 取同一个全局实例即可。
"""
from app.services.llm_service import LLMService
from app.services.retrieval_service import RetrievalService
from app.services.validation_service import ValidationService

__all__ = ["LLMService", "RetrievalService", "ValidationService"]
