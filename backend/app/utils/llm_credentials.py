"""当前调用链使用的大模型凭据（ContextVar 透传，纯 Python 不依赖 sqlalchemy）。

为什么和 token_usage 一样走 ContextVar：后台生成任务里 LLMService 在 clarify、
模块拆分、各并行模块、评审、补充等多处各自 new，其中多数还跑在 create_task 起的
并发 worker 里。HTTP 请求期解析一次凭据（个人配置或系统兜底）并快照进任务，
TaskManager._run 在起任何 worker 之前 bind 一次，所有并发调用经 ContextVar 取到
同一份——不用改遍 worker 签名与 _parallel_agents 协议。

后台任务比 HTTP 请求长寿，故凭据必须在创建任务时快照，不能在 worker 里依赖登录态。
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


class CredentialNotConfiguredError(Exception):
    """个人凭据与系统兜底都未配置时抛出。消息面向用户，引导去设置页填写。"""


@dataclass(frozen=True)
class LLMCredentials:
    base_url: str
    api_key: str
    model: str
    # 'user' = 用户个人配置的 key（花自己的额度）；'system' = 全局兜底模型。
    source: str

    def normalized(self) -> "LLMCredentials":
        return LLMCredentials(
            base_url=self.base_url.rstrip("/"),
            api_key=self.api_key,
            model=self.model,
            source=self.source,
        )


_current: ContextVar[LLMCredentials | None] = ContextVar("llm_credentials", default=None)


@contextmanager
def bind(creds: LLMCredentials | None) -> Iterator[None]:
    """在当前上下文绑定凭据；creds 为 None 时等价于不绑（图片 OCR 等可选场景）。"""
    if creds is None:
        yield
        return
    token = _current.set(creds)
    try:
        yield
    finally:
        _current.reset(token)


def get_optional() -> LLMCredentials | None:
    return _current.get()


def get_required() -> LLMCredentials:
    creds = _current.get()
    if creds is None:
        raise CredentialNotConfiguredError(
            "尚未配置大模型凭据，请先到「设置」页填写 base_url / API Key / 模型名"
        )
    return creds
