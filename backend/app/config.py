from pathlib import Path

from pydantic_settings import BaseSettings

# 按 backend 目录定位 .env 文件
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


_BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    DATABASE_URL: str = f"sqlite+aiosqlite:///{_BASE_DIR}/data/testcase_platform.db"
    CHROMA_PERSIST_DIR: str = str(_BASE_DIR / "data" / "chromadb")
    UPLOAD_DIR: str = str(_BASE_DIR / "uploads")

    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-3.5-turbo"

    LLM_TEMPERATURE: float = 0.3
    LLM_MAX_TOKENS: int = 8192
    # 推理强度（OpenAI 兼容协议下的 reasoning_effort 字段）。
    #   ""      = 不带该字段（默认，兼容所有 OpenAI-compat 模型）
    #   "low" / "medium" / "high" / "max" = 让支持的模型走对应思考强度
    # 目前主要影响 DeepSeek V4 Pro/Flash 等具备"Think"模式的模型；不识别该字段的服务商会忽略。
    LLM_REASONING_EFFORT: str = ""

    # 是否采集 token 用量（流式请求带 stream_options.include_usage，把服务端上报的
    # usage 记入 llm_usage 表，供看板展示今日/本周/累计消耗与阶段占比）。
    #   True（默认）= 采集。多出的字段对不支持的服务商是无害的未知字段，会被忽略。
    #   False = 不带该字段、不记流水。个别服务商对未知字段返回 400 时用它一键回退。
    LLM_COLLECT_TOKEN_USAGE: bool = True

    # ── 分批生成（避免单次响应撞满 max_tokens 被截断）──
    # LLM_ENABLE_MODULE_SPLIT：是否先抽取【模块清单】再按模块分批生成。
    #   True（默认）= 大需求拆成多批，每批更聚焦、更不易截断；抽出的模块 ≤1 个时自动退化为单批。
    #   False = 关闭模块分批，只保留「续写式」兜底（撞满 max_tokens 就续写）。出问题可一键回退。
    LLM_ENABLE_MODULE_SPLIT: bool = True
    # 需求文本长度低于此值（字符数）时跳过模块拆分，直接单批生成。
    # 小需求单批生成本就撑不满 max_tokens，抽模块只会白花一次 LLM 调用。
    # 续写式兜底始终生效，跳过不影响防截断，所以阈值可以定宽些。
    LLM_MODULE_SPLIT_MIN_CHARS: int = 4000
    # 单批被 max_tokens 截断后，最多自动续写几轮（防止极端情况下无限续写）。
    LLM_MAX_CONTINUATIONS: int = 3

    # 模块并行生成：最多同时向 LLM 发起几个模块的生成请求。
    # 受套餐并发额度限制，出现 429 时应调小；配合 429 退避重试兜底。
    # 注：评审/补充阶段也复用此并发上限（v0.16 起按模块并行）。
    LLM_MODULE_CONCURRENCY: int = 5
    # 每个模块的启动错峰间隔（秒）：并发启动时逐个延迟，避免同一瞬间大量请求
    # 撞到限流上限（RPS 突刺）。第 n 个模块延迟 n * 该值后再发起。
    # 注：评审/补充阶段也复用此错峰间隔（v0.16 起按模块并行）。
    LLM_MODULE_STAGGER_DELAY: float = 0.5
    # 评审分组的「组内条数上限」**兜底值**：评审按【】里的前两级模块路径分组，仅当单个
    # 二级模块仍超过此值时才按条数均分切块。v0.16 曾弃用（纯按顶层模块分组），但顶层
    # 分组挡不住超大模块——上千条的批次会被压成两三组，评审响应必然撞满 max_tokens
    # 截断、整组判定静默丢失，故 v0.25 重新启用。两级分组后此值很少触发（实测 1097 条
    # 的批次最大组仅 107 条），主要用于兜住单个二级模块异常膨胀的极端情况。
    LLM_REVIEW_BATCH_SIZE: int = 200

    # 向量检索阈值（L2 距离）：最小结果超过此值视为"完全不相关"，整批过滤。
    VECTOR_MIN_DISTANCE_THRESHOLD: float = 12.0
    # 在"有相关性"的前提下，保留距离不超过「最小距离 + 此增量」的结果。
    VECTOR_DISTANCE_DELTA: float = 4.0

    # 飞书开放平台自建应用凭证。空值表示未配置，接入接口会直接报错。
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""
    FEISHU_OPEN_API_BASE: str = "https://open.feishu.cn/open-apis"

    model_config = {"env_file": str(_ENV_PATH), "env_file_encoding": "utf-8"}


settings = Settings()
