import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, now_local


class LlmUsage(Base):
    """一次 LLM 调用的 token 消耗流水。

    一行 = 一次 chat/completions 请求（含续写的每一轮、每个并行模块各自一行），
    看板的「今日/本周/累计」与阶段占比都由这张表聚合而来。

    为什么不挂外键到 test_cases/batch：调用与用例不是一对一（模块拆分、评审、
    补充都不直接产出某条用例），且 clarify 阶段压根没有批次。batch_id 只做可空
    标注，聚合时按它 GROUP BY 即可，缺失的归入「未关联批次」。

    created_at 走 database.now_local()，即 naive 的 Asia/Shanghai 时间，与
    test_cases.created_at 同口径——「今日/本周」直接按日期比较，无需时区换算。
    """

    __tablename__ = "llm_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # 产出阶段，与生成流程的 stage 命名对齐：
    #   clarify / module_split / generate / review / supplement
    # 看板按此维度拆分占比，用来回答「钱花在哪个环节」。
    stage: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 推理模型的思考 token（DeepSeek/o 系列在 usage.completion_tokens_details 里上报）。
    # 已包含在 completion_tokens 内，单独存一份用于回答「思考占了多少」——
    # 这正是 LLM_REASONING_EFFORT=max 值不值的判据。服务端不报时为 0。
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 归属的生成批次。生成任务落库拿到 batch_id 后由 task_service 回填，
    # clarify 等无批次的调用留 NULL。
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, index=True)
