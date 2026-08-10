import asyncio
import json
import logging
import os
from typing import AsyncGenerator

import httpx

from app.config import settings
# 只用采集函数，故直接指向纯逻辑模块而不是 services.usage_service——后者依赖
# sqlalchemy，而 CI 只装 pytest，从这里牵进 sqlalchemy 会让轻量测试无法 import。
from app.utils import token_usage


logger = logging.getLogger(__name__)


_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)

# 遇到服务端临时不可用(5xx)或限流(429)时的自动重试策略：指数退避。
# 429 加入重试是因为并行化后可能偶发撞限流，自动等待后重试即可恢复；
# 若持续 429 且套餐额度已用尽，重试也无用，让上层在超限后抛明确提示。
_RETRY_STATUS = {429, 502, 503, 504}
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
        # 最近一次流式生成结束时服务端上报的 finish_reason。
        #   "stop"   = 模型自然写完
        #   "length" = 撞满 max_tokens 被截断（续写分批的判据）
        #   None     = 服务端未上报（部分 OpenAI-compat 服务不带该字段）
        # 每次 generate_stream 开头重置，上层在 async-for 结束后读取。
        self.last_finish_reason: str | None = None

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
            # 请服务端在流的最后一个 chunk 带上 usage（OpenAI 兼容协议约定）。
            # 流式默认不返回 usage，不加这个字段就统计不到 token 消耗。
            # 个别服务商不认这个字段——多数会忽略，但若遇到直接报 400 的，
            # 把 LLM_COLLECT_TOKEN_USAGE 置 False 一键关掉即可。
            if settings.LLM_COLLECT_TOKEN_USAGE:
                payload["stream_options"] = {"include_usage": True}
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

    async def generate_stream(self, system_content: str, user_content: str,
                              on_reasoning=None) -> AsyncGenerator[str, None]:
        """通过 SSE 流式生成。

        on_reasoning 非空时，每收到一段 reasoning_content（模型思考）就以其为参数调用
        （可为 async）。注意：思考文本【只】通过该回调外发，绝不 yield——yield 出去的
        始终只是正文 content，避免思考被当作用例喂给解析器。reasoning=max 下模型会先
        长时间思考、正文全程为空，这段时间若不外发思考，上层就完全没有反馈（前端表现为
        "等待模型输出"）。有了 on_reasoning，上层可实时展示"思考中"的流。
        """
        messages = self._build_messages(system_content, user_content)
        # 每次调用先重置，避免上一次的 finish_reason 泄漏到本次判断。
        self.last_finish_reason = None

        timeout = httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=15.0)
        # 是否已向上游 yield 过任何内容。超时重试只在「还没吐出任何内容」时才安全——
        # 否则重试会让已发出的片段重复。评审等大 prompt 调用常在首字节前慢导致超时，
        # 这类「空手超时」重试一次往往就能过。
        emitted_any = False
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
                            backoff = _backoff_seconds(attempt, response)
                            logger.warning(
                                "模型请求撞限流/暂不可用 status=%s，第 %d 次退避重试，等待 %.2fs",
                                response.status_code, attempt + 1, backoff,
                            )
                            await response.aread()
                            await asyncio.sleep(backoff)
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
                                    # usage 必须在取 choices[0] 之前处理：带 usage 的那个
                                    # chunk 里 choices 是空数组，先 data["choices"][0] 会抛
                                    # IndexError 被下面的 except 吞掉，usage 就永远采不到。
                                    if data.get("usage"):
                                        token_usage.record(self.model, data["usage"])
                                    if not data.get("choices"):
                                        continue
                                    choice = data["choices"][0]
                                    # 记录 finish_reason：多数服务在最后一个 chunk 才带非空值，
                                    # 逐 chunk 覆盖即可拿到最终值（续写分批据此判断是否被截断）。
                                    fr = choice.get("finish_reason")
                                    if fr:
                                        self.last_finish_reason = fr
                                    delta = choice.get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        content_seen = True
                                        emitted_any = True
                                        yield content
                                        continue
                                    reasoning = delta.get("reasoning_content", "")
                                    if reasoning:
                                        reasoning_buf += reasoning
                                        if on_reasoning is not None:
                                            res = on_reasoning(reasoning)
                                            if asyncio.iscoroutine(res):
                                                await res
                                except (json.JSONDecodeError, KeyError, IndexError):
                                    continue
                        if not content_seen and reasoning_buf and _looks_like_structured_output(reasoning_buf):
                            emitted_any = True
                            yield reasoning_buf
                        return
                except httpx.TimeoutException as exc:
                    # 空手超时（还没吐任何内容）且有重试额度：退避后重试。
                    # 已吐过内容再超时则不能重试（会重复），直接抛错。
                    if not emitted_any and attempt < _MAX_RETRIES:
                        await asyncio.sleep(_backoff_seconds(attempt))
                        continue
                    raise LLMServiceError("模型响应超时，请稍后重试或缩短需求描述") from exc
                except httpx.RequestError as exc:
                    raise LLMServiceError(f"无法连接模型服务：{exc}") from exc
