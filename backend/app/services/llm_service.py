import asyncio
import json
import os
from typing import AsyncGenerator

import httpx

from app.config import settings


_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)

# 遇到服务端临时不可用(5xx)时的自动重试策略：指数退避。
# 429（限流/额度超限）不重试——重试也无用，直接返回明确提示，避免白等。
_RETRY_STATUS = {502, 503, 504}
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # 秒；第 n 次重试等待 base * 2**n，即 2/4/8s


def _remove_proxy_env() -> None:
    for name in _PROXY_ENV_VARS:
        os.environ.pop(name, None)


def _backoff_seconds(attempt: int, response: httpx.Response | None = None) -> float:
    """计算重试等待秒数：优先遵循服务端 Retry-After 头，否则指数退避。attempt 从 0 起。"""
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 30.0)
            except ValueError:
                pass
    return _BACKOFF_BASE * (2 ** attempt)


class LLMServiceError(Exception):
    """模型服务调用失败时抛出，携带面向用户的中文提示。"""


class LLMService:
    """LLM API 封装，兼容 OpenAI 接口并支持流式输出。"""

    def __init__(self):
        _remove_proxy_env()
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL.rstrip("/")
        self.model = settings.LLM_MODEL
        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS

    def _build_messages(self, system_content: str, user_content: str) -> list[dict]:
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

    async def generate(self, system_content: str, user_content: str) -> str:
        """同步生成，非流式返回。"""
        messages = self._build_messages(system_content, user_content)

        # 推理类模型（如 GLM-4.5）会先输出较长的 reasoning_content，再生成正文，
        # 总耗时可能很长。连接超时保持短，读超时拉长到 300s 以避免 ReadTimeout。
        timeout = httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(_MAX_RETRIES + 1):
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.model,
                            "messages": messages,
                            "temperature": self.temperature,
                            "max_tokens": self.max_tokens,
                        },
                    )
                except httpx.TimeoutException as exc:
                    raise LLMServiceError("模型响应超时，请稍后重试或缩短需求描述") from exc
                except httpx.RequestError as exc:
                    raise LLMServiceError(f"无法连接模型服务：{exc}") from exc

                # 服务端瞬时错误（502/503/504）：指数退避后重试。
                if response.status_code in _RETRY_STATUS and attempt < _MAX_RETRIES:
                    await asyncio.sleep(_backoff_seconds(attempt, response))
                    continue

                if response.status_code != 200:
                    detail = response.text[:300]
                    if response.status_code == 429:
                        raise LLMServiceError("模型调用受限（429）：可能是当前额度/配额已用尽或并发超限，请检查账户用量或更换模型")
                    raise LLMServiceError(f"模型服务返回错误 {response.status_code}：{detail}")

                data = response.json()
                return self._extract_content(data)

    @staticmethod
    def _extract_content(data: dict) -> str:
        """提取生成正文；正文为空时退回 reasoning_content（推理模型）。"""
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise LLMServiceError("模型返回格式异常，缺少 choices/message") from exc
        content = message.get("content") or ""
        if not content.strip():
            content = message.get("reasoning_content") or ""
        return content

    async def generate_stream(self, system_content: str, user_content: str) -> AsyncGenerator[str, None]:
        """通过 SSE 流式生成。"""
        messages = self._build_messages(system_content, user_content)

        timeout = httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(_MAX_RETRIES + 1):
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": self.temperature,
                        "max_tokens": self.max_tokens,
                        "stream": True,
                    },
                ) as response:
                    # 限流/暂时不可用：读掉响应体释放连接后指数退避重试。
                    if response.status_code in _RETRY_STATUS and attempt < _MAX_RETRIES:
                        await response.aread()
                        await asyncio.sleep(_backoff_seconds(attempt, response))
                        continue
                    if response.status_code != 200:
                        await response.aread()
                        if response.status_code == 429:
                            raise LLMServiceError("模型调用受限（429）：可能是当前额度/配额已用尽或并发超限，请检查账户用量或更换模型")
                        raise LLMServiceError(f"模型服务返回错误 {response.status_code}")
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            chunk = line[6:]
                            if chunk == "[DONE]":
                                break
                            try:
                                data = json.loads(chunk)
                                delta = data["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except (json.JSONDecodeError, KeyError, IndexError):
                                continue
                    return
