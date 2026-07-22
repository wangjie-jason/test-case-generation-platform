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
