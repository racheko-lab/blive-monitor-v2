# blive-monitor 后端镜像（阶段四）
# 基于 python:3.11-slim，提供 FastAPI + SQLite 持久化后端。
FROM python:3.11-slim

WORKDIR /app

# 先装依赖（利用层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝全部源码（不含 .dockerignore 排除项）
COPY . .

# 持久化挂载点：sqlite 库 / 封面转存
RUN mkdir -p /app/data /app/assets/covers

ENV BLIVE_DB_PATH=/app/data/blive.db \
    BLIVE_COVERS_DIR=/app/assets/covers \
    TZ=Asia/Shanghai

EXPOSE 8000

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
