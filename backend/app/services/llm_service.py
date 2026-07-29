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


def _looks_like_structured_output(text: str) -> bool:
    """判断一段文本是否值得当作模型的"结构化输出"喂给下游解析器。
    只要包含 JSON 起始符（{ 或 [）就认为可能藏着可解析的用例。纯自然语言规划
    （"1. 理解目标..."）不包含这两个符号，会被过滤掉。"""
    return "{" in text or "[" in text


class LLMService:
    """LLM API 封装，兼容 OpenAI 接口并支持流式输出。"""

    def __init__(self):
        _remove_proxy_env()
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL.rstrip("/")
        self.model = settings.LLM_MODEL
        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS
        self.reasoning_effort = settings.LLM_REASONING_EFFORT.strip() or None

    def _build_payload(self, messages: list[dict], stream: bool = False) -> dict:
        """构造 chat/completions 请求体；仅当配置了推理强度时才带 reasoning_effort。"""
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if stream:
            payload["stream"] = True
        if self.reasoning_effort:
            # OpenAI 兼容协议下的思考强度字段。不支持的服务商会自动忽略，安全。
            payload["reasoning_effort"] = self.reasoning_effort
        return payload

    def _build_messages(self, system_content: str, user_content: str) -> list[dict]:
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

    async def generate(self, system_content: str, user_content: str) -> str:
        """同步生成，返回完整正文。

        内部复用流式 SSE 路径累积成整段字符串，而非发一次非流式请求。原因：非流式
        请求要等服务端把整段响应（含推理模型很长的 reasoning_content）全部生成完才返回，
        等于一次性 read——推理模型思考稍久就会撞满 read 超时抛 ReadTimeout（评审阶段的
        典型故障）。流式下服务端持续吐 token，read 超时是"两次 chunk 之间的间隔"，几乎
        不会触发；且能顺带复用 generate_stream 里的 reasoning_content 兜底逻辑。
        """
        chunks: list[str] = []
        async for chunk in self.generate_stream(system_content, user_content):
            chunks.append(chunk)
        return "".join(chunks)

    async def generate_stream(self, system_content: str, user_content: str) -> AsyncGenerator[str, None]:
        """通过 SSE 流式生成。"""
        messages = self._build_messages(system_content, user_content)

        timeout = httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=15.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            for attempt in range(_MAX_RETRIES + 1):
                # 把 httpx 的超时/网络异常转成携带中文提示的 LLMServiceError。
                # 这层转换过去只在非流式 generate 里有；如今 generate 也走本方法，
                # 且上层（task_service / generation 路由）只捕获 LLMServiceError——
                # 不转换的话，流式路径一旦超时会抛原始 httpx 异常，直接漏网。
                try:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=self._build_payload(messages, stream=True),
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
                        # 推理模型在流式下常常把正文放进 delta.reasoning_content，delta.content 全程为空。
                        # 若整段流下来一个 content 都没有，把累积的 reasoning_content 作为兜底一次性 yield，
                        # 避免上层拿到空串（非流式 generate 现已复用本方法，同样受益）。
                        # 但要收紧：只有 reasoning 里出现过 JSON 起始符时才 yield，否则说明模型全程都在
                        # 输出自然语言规划（思考爆了 max_tokens，还没进入正文），这种情况把思考文本喂给
                        # 用例解析器一定是垃圾进垃圾出，还不如让上层清晰地拿到空串，报"模型只思考未输出"。
                        content_seen = False
                        reasoning_buf = ""
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
                                        content_seen = True
                                        yield content
                                        continue
                                    reasoning = delta.get("reasoning_content", "")
                                    if reasoning:
                                        reasoning_buf += reasoning
                                except (json.JSONDecodeError, KeyError, IndexError):
                                    continue
                        if not content_seen and reasoning_buf and _looks_like_structured_output(reasoning_buf):
                            yield reasoning_buf
                        return
                except httpx.TimeoutException as exc:
                    raise LLMServiceError("模型响应超时，请稍后重试或缩短需求描述") from exc
                except httpx.RequestError as exc:
                    raise LLMServiceError(f"无法连接模型服务：{exc}") from exc
