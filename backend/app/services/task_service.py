import asyncio
import json
import logging
import uuid as _uuid

from app.database import async_session, now_local
from app.models.test_case import TestCase
from app.services.generator_service import GeneratorService
from app.services.indexing_service import IndexingService
from app.services.llm_service import LLMServiceError

logger = logging.getLogger(__name__)

# 已完成任务在内存中保留的时长（秒）。超过后由新任务创建时顺带清理，
# 避免长时间运行积累过多历史任务占用内存。
_DONE_TTL_SECONDS = 3600
# 内存中保留任务的最大数量上限（含运行中与已完成），超过则淘汰最旧的已完成任务。
_MAX_TASKS = 50

_END = {"type": "__end__"}


async def persist_cases(db, cases: list[dict], batch_name: str | None, requirement_text: str) -> str:
    """将生成的用例写入数据库，返回 batch_id。"""
    batch_id = str(_uuid.uuid4())
    created = []
    for c in cases:
        steps = c.get("steps", "")
        if isinstance(steps, list):
            steps = json.dumps(steps, ensure_ascii=False)
        tc = TestCase(
            title=c.get("title", ""), precondition=c.get("precondition", ""),
            steps=steps, expected_result=c.get("expected_result", ""),
            source="ai", batch_id=batch_id, req_text=batch_name or requirement_text[:80],
            knowledge_refs=json.dumps(c.get("knowledge_refs", []), ensure_ascii=False),
        )
        db.add(tc)
        created.append(tc)
    await db.commit()
    # 生成的用例回灌历史用例向量库，作为后续生成的 few-shot 语料。
    for tc in created:
        await IndexingService.index_case(tc)
    return batch_id


class GenerationTask:
    """一次后台生成任务。事件被缓存在 events 中，支持断线/刷新后重连重放。"""

    def __init__(self, requirement_text: str, batch_name: str | None, kb_ids: list[str] | None):
        self.id = str(_uuid.uuid4())
        self.requirement_text = requirement_text
        self.batch_name = batch_name
        self.kb_ids = kb_ids
        self.title = (batch_name or requirement_text or "").strip()[:40] or "未命名需求"
        self.created_at = now_local()
        self.status = "running"  # running | done | error
        self.events: list[dict] = []
        self._subscribers: list[asyncio.Queue] = []
        self.done = False

    def _emit(self, event: dict) -> None:
        self.events.append(event)
        for q in self._subscribers:
            q.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        """订阅事件流：先把已缓存的历史事件入队（用于重放），再接收后续实时事件。"""
        q: asyncio.Queue = asyncio.Queue()
        for e in self.events:
            q.put_nowait(e)
        if self.done:
            q.put_nowait(_END)
        else:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def summary(self) -> dict:
        return {
            "task_id": self.id,
            "title": self.title,
            "status": self.status,
            "created_at": str(self.created_at),
        }


class TaskManager:
    _tasks: dict[str, GenerationTask] = {}

    @classmethod
    def create(cls, requirement_text: str, batch_name: str | None, kb_ids: list[str] | None) -> GenerationTask:
        cls._prune()
        task = GenerationTask(requirement_text, batch_name, kb_ids)
        cls._tasks[task.id] = task
        asyncio.create_task(cls._run(task))
        return task

    @classmethod
    def get(cls, task_id: str) -> GenerationTask | None:
        return cls._tasks.get(task_id)

    @classmethod
    def active(cls) -> list[GenerationTask]:
        """返回运行中的任务（最近创建的在前），供前端提供「继续查看」入口。"""
        running = [t for t in cls._tasks.values() if t.status == "running"]
        return sorted(running, key=lambda t: t.created_at, reverse=True)

    @classmethod
    async def _run(cls, task: GenerationTask) -> None:
        # 使用独立的 DB 会话，使任务脱离 HTTP 请求生命周期：客户端断开/刷新后任务继续。
        try:
            async with async_session() as db:
                async for event in GeneratorService.generate_stream(
                    db, task.requirement_text, kb_ids=task.kb_ids or None
                ):
                    if event.get("type") == "complete":
                        await persist_cases(db, event.get("cases", []), task.batch_name, task.requirement_text)
                    task._emit(event)
            task.status = "done"
        except LLMServiceError as exc:
            task._emit({"type": "error", "message": str(exc)})
            task.status = "error"
        except Exception as exc:  # noqa: BLE001 后台任务兜底，避免静默失败
            logger.exception("生成任务失败 task_id=%s", task.id)
            task._emit({"type": "error", "message": f"生成失败：{exc}"})
            task.status = "error"
        finally:
            task.done = True
            for q in task._subscribers:
                q.put_nowait(_END)
            task._subscribers.clear()

    @classmethod
    def _prune(cls) -> None:
        now = now_local()
        # 清理超过 TTL 的已完成任务
        expired = [
            tid for tid, t in cls._tasks.items()
            if t.done and (now - t.created_at).total_seconds() > _DONE_TTL_SECONDS
        ]
        for tid in expired:
            cls._tasks.pop(tid, None)
        # 数量仍超限时，从最旧的已完成任务开始淘汰
        if len(cls._tasks) >= _MAX_TASKS:
            done_oldest = sorted(
                (t for t in cls._tasks.values() if t.done),
                key=lambda t: t.created_at,
            )
            for t in done_oldest:
                if len(cls._tasks) < _MAX_TASKS:
                    break
                cls._tasks.pop(t.id, None)
