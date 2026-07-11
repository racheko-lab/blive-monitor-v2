"""调度器注册表：持有当前激活的 Scheduler 实例（由 app lifespan 注入）。

避免 API 层与调度层循环依赖：jobs_api 通过本模块取得运行中的 Scheduler。
"""

from typing import Optional

_ACTIVE: Optional[object] = None


def set_scheduler(scheduler) -> None:
    global _ACTIVE
    _ACTIVE = scheduler


def get_scheduler():
    return _ACTIVE
