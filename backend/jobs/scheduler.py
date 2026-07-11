"""Scheduler：APScheduler（AsyncIOScheduler）自驱检测调度（设计 §1.3 / §3.4）。

- live_check：每 LIVE_CHECK_INTERVAL_MIN（默认 5）分钟一轮；每轮结束后顺带评估 summary
  （设计 §8.10「每轮惰性 should_deliver 评估」，免去动态 cron）。
- post_check：每 POST_CHECK_INTERVAL_MIN（默认 10）分钟一轮，**仅当 ENABLE_POST_CHECK=true**。
- transcode：在 post_check 轮内顺带执行（无需独立触发器）。
- 重叠保护：RUNNING_FLAGS 防重入 + coalesce=True + misfire_grace_time=60。
- 手动触发：trigger(type) 经 asyncio 在当前事件循环异步拉起一轮。
"""

import asyncio
import logging
from typing import Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .. import config
from .detection_service import DetectionService

logger = logging.getLogger(__name__)

# 任务级重入锁（防重叠）。
RUNNING_FLAGS: Dict[str, bool] = {
    "live": False,
    "post": False,
    "summary": False,
    "transcode": False,
}


class Scheduler:
    """APScheduler 封装。"""

    def __init__(self, detection: DetectionService = None):
        self.detection = detection or DetectionService()
        self._aps = AsyncIOScheduler(timezone=config.TZ)
        self._loop = None

    # ---------- 包装：重入保护 + 异常隔离 ----------
    async def _guarded(self, name: str, coro_fn) -> None:
        if RUNNING_FLAGS.get(name):
            logger.info("[scheduler] 跳过 %s（上一轮尚未完成，防重叠）", name)
            return
        RUNNING_FLAGS[name] = True
        try:
            await asyncio.to_thread(coro_fn)
        except Exception as e:  # 单轮异常不应打断调度器
            logger.exception("[scheduler] %s 执行异常: %s", name, e)
        finally:
            RUNNING_FLAGS[name] = False

    async def _live_job(self) -> None:
        await self._guarded("live", self.detection.run_live)
        # 每轮 live 之后惰性评估摘要投递（§8.10）
        await self._guarded("summary", self.detection.run_summary)

    async def _post_job(self) -> None:
        await self._guarded("post", self.detection.run_post)
        # transcode 在 post 轮内顺带执行
        await self._guarded("transcode", self.detection.run_transcode)

    # ---------- 生命周期 ----------
    def start(self) -> None:
        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

        self._aps.add_job(
            self._live_job,
            IntervalTrigger(minutes=config.LIVE_CHECK_INTERVAL_MIN),
            id="live",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=config.MISFIRE_GRACE_SEC,
        )
        if config.ENABLE_POST_CHECK:
            self._aps.add_job(
                self._post_job,
                IntervalTrigger(minutes=config.POST_CHECK_INTERVAL_MIN),
                id="post",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=config.MISFIRE_GRACE_SEC,
            )
        else:
            logger.info("[scheduler] ENABLE_POST_CHECK=false，未注册 post_check 任务")

        self._aps.start()
        logger.info("[scheduler] 已启动（live=%dmin, post=%dmin, post_enabled=%s）",
                    config.LIVE_CHECK_INTERVAL_MIN, config.POST_CHECK_INTERVAL_MIN,
                    config.ENABLE_POST_CHECK)

    def shutdown(self) -> None:
        try:
            self._aps.shutdown(wait=False)
        except Exception as e:
            logger.warning("[scheduler] shutdown 异常: %s", e)
        logger.info("[scheduler] 已停止")

    def trigger(self, type_: str) -> None:
        """手动触发一轮（P1）。type_ ∈ {'live','post','all'}。

        若调度器已绑定事件循环（lifespan 启动后），经 run_coroutine_threadsafe 异步拉起；
        否则（如测试中未启动）落到一个临时事件循环里同步跑完，便于断言。
        """

        async def _run():
            if type_ in ("live", "all"):
                await self._live_job()
            if type_ in ("post", "all"):
                await self._post_job()

        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(_run(), self._loop)
        else:
            # 无事件循环（未 start）：起一个临时 loop 跑完。
            asyncio.run(_run())
