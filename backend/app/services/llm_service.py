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


def _remove_proxy_env() -> None:
    for name in _PROXY_ENV_VARS:
        os.environ.pop(name, None)


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

            if response.status_code != 200:
                detail = response.text[:300]
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
                response.raise_for_status()
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
