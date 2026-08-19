from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import run_migrations


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    Path("./data").mkdir(parents=True, exist_ok=True)
    # 起服务即自动建表/补列（老库自动识别并补 stamp 标记），无需手工执行 alembic 命令。
    run_migrations()
    yield


app = FastAPI(title="Test Case Generation Platform", version="0.5.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

from app.routers import generation, knowledge  # noqa: E402

app.include_router(knowledge.router, prefix="/api/v1", tags=["知识库"])
app.include_router(generation.router, prefix="/api/v1", tags=["用例生成"])


@app.get("/api/health")
async def health(): return {"status": "ok"}
