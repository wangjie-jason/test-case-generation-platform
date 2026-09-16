from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI

from app.config import settings
from app.database import async_session, run_migrations
from app.routers.deps import get_current_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    Path("./data").mkdir(parents=True, exist_ok=True)
    # 起服务即自动建表/补列（老库自动识别并补 stamp 标记），无需手工执行 alembic 命令。
    run_migrations()
    # 双保险：确保 .env 配置的首个管理员存在（迁移在全新库上已建过）。
    from app.services import auth_service
    async with async_session() as db:
        await auth_service.ensure_admin(db)
    yield


app = FastAPI(title="Test Case Generation Platform", version="0.5.0", lifespan=lifespan)

# 开发走 Vite 同源代理、生产走前端容器 nginx 反代，没有跨域消费者，故不需要 CORS。

from app.routers import admin_users, auth, generation, knowledge, llm_config  # noqa: E402

# 认证与用户管理接口自己挂依赖（login 必须公开）。
app.include_router(auth.router, prefix="/api/v1", tags=["认证"])
app.include_router(admin_users.router, prefix="/api/v1")
app.include_router(llm_config.router, prefix="/api/v1")

# 业务 router 全量强制登录：统一在 include 时挂依赖，新增端点天然受保护。
_auth = [Depends(get_current_user)]
app.include_router(knowledge.router, prefix="/api/v1", tags=["知识库"], dependencies=_auth)
app.include_router(generation.router, prefix="/api/v1", tags=["用例生成"], dependencies=_auth)


@app.get("/api/health")
async def health(): return {"status": "ok"}
