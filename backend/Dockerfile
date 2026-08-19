FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data /app/uploads

EXPOSE 8000
# 迁移由应用启动时自动执行（lifespan 里的 run_migrations，老库自动识别），无需前置 alembic 命令。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
