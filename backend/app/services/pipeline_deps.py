"""生成流水线的外部依赖接缝。

各 stage 模块一律通过 `deps.LLMService()` / `deps.RetrievalService` / `deps.ValidationService`
调用外部服务，而不是直接 import 它们。

`LLMService` 在这里是**零参工厂函数**而非类：实例所需的用户凭据（api_key/base_url/model）
来自当前上下文绑定的 `app.utils.llm_credentials`（HTTP 请求期或后台任务开跑前 bind），
工厂只负责在调用时 new 出实例。调用点写法 `deps.LLMService()` 与原来是类时完全一致。
每个并行模块/评审/补充 worker 各自经工厂拿到独立实例（续写依赖实例级 last_finish_reason）。

本模块只 import 叶子服务，**绝不 import 任何 pipeline_* 模块**：这条单向约束修掉过一个
真实的循环导入——此前接缝挂在 `generator_service` 上，stage 模块反过来
`import app.services.generator_service as _gs`，与 generator_service 对 stage 模块的
正向 import 成环，实测 5 个 pipeline 模块全都无法独立 import，只因运行时入口恰好先
import generator_service 才没暴雷。接缝下沉后依赖单向：
generator_service → pipeline_service → pipeline_*_service → pipeline_deps → 叶子服务。

`settings` 不在这里：各模块直接 `from app.config import settings` 取全局同一个实例即可。
"""
from app.services.llm_service import LLMService as _LLMServiceImpl
from app.services.retrieval_service import RetrievalService
from app.services.validation_service import ValidationService


def LLMService():
    """按当前上下文绑定的凭据构造一个 LLMService。未绑定凭据时由其构造函数报错。"""
    return _LLMServiceImpl()


__all__ = ["LLMService", "RetrievalService", "ValidationService"]
