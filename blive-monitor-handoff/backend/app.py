"""FastAPI 应用入口（阶段四 T01 / T05 收尾）。

职责（见 docs/phase4_design.md §1.1 / §3.3）：
  - 创建 ``FastAPI`` 实例，挂载 ``backend/api`` 下全部 router 到 ``/api/v1`` 前缀。
  - ``GET /healthz`` 返回 ``{"status": "ok"}``（鉴权豁免）。
  - 启动时 ``db.init_db()`` 建表（幂等）；按需启动 Scheduler（默认不自启，避免测试 /
    import / 迁移脚本自启，由环境变量 ``START_SCHEDULER`` 控制）。
  - 写接口鉴权由各 router 的 ``require_auth`` 依赖处理（``AUTH_TOKEN`` 空则放行）。

设计要点：
  - 路由处理器一律用 ``def``（同步），FastAPI 自动丢线程池，与 sync SQLAlchemy 天然契合。
  - 鉴权粒度（§8.7）：``AUTH_TOKEN`` 为空放行；非空时校验请求头 ``X-Bearer-Token``；
    ``/healthz`` 与只读接口豁免（读路由不挂 ``require_auth`` 依赖）。
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from . import config, db
from .api import (
    config_api,
    events,
    jobs_api,
    notify,
    posts,
    rooms,
    silence_api,
    summary_api,
)
from .jobs.registry import get_scheduler, set_scheduler
from .jobs.scheduler import Scheduler

logger = logging.getLogger(__name__)

# API 前缀（设计 §3.3：/api/v1）。显式常量，确保与前端/设计契约一致、不受 env 影响。
API_PREFIX = "/api/v1"


def _should_start_scheduler() -> bool:
    """是否自启 Scheduler：仅当 ``START_SCHEDULER`` 显式为真值时启动。

    默认（未设置 / 空 / false）不自启，便于测试、``import backend.app``、迁移脚本等场景。
    """
    v = os.environ.get("START_SCHEDULER")
    if not v:
        return False
    return v.strip().lower() in ("1", "true", "yes", "on")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ① 建表（幂等，SQLAlchemy Base.metadata.create_all）。
    db.init_db()
    logger.info("[app] 数据库表已就绪（engine=%s）", config.DB_PATH)

    scheduler: Optional[Scheduler] = None
    if _should_start_scheduler():
        scheduler = Scheduler()
        set_scheduler(scheduler)
        scheduler.start()
        logger.info("[app] Scheduler 已启动")
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown()
            set_scheduler(None)
            logger.info("[app] Scheduler 已停止")


app = FastAPI(
    title="blive-monitor backend",
    version="0.4.0",
    description="阶段四后端基座：直播 / 新作监控持久化（SQLite）+ REST API + 自驱调度",
    lifespan=lifespan,
)

# 挂载全部 router 到 /api/v1。
app.include_router(rooms.router, prefix=API_PREFIX)
app.include_router(posts.router, prefix=API_PREFIX)
app.include_router(events.router, prefix=API_PREFIX)
app.include_router(notify.router, prefix=API_PREFIX)
app.include_router(config_api.router, prefix=API_PREFIX)
app.include_router(summary_api.router, prefix=API_PREFIX)
app.include_router(silence_api.router, prefix=API_PREFIX)
app.include_router(jobs_api.router, prefix=API_PREFIX)


@app.get("/healthz")
def healthz() -> dict:
    """健康检查（鉴权豁免）。

    Returns:
        ``{"status": "ok"}``（设计 §3.3）。
    """
    return {"status": "ok"}
