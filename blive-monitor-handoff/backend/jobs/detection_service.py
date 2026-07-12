"""DetectionService：一轮检测的编排入口（设计 §3.2）。

组合 ConfigStore + 各类 Persist 门面 + 现有检测模块（check_status /
check_new_posts / auto_summary）的 ``run_*`` 纯编排函数。抓取/路由/模板/推送逻辑
全部复用现有模块，本类仅负责「读配置 → 调用检测 → 经门面落库」。
"""

import logging
from typing import Any, Optional

from ..config_store import ConfigStore
from .live_check import LivePersist
from .post_check import PostPersist
from .summary_job import SummaryPersist

logger = logging.getLogger(__name__)


class DetectionService:
    """一轮检测编排。"""

    def __init__(self, config_store: Optional[ConfigStore] = None):
        self.config_store = config_store or ConfigStore()

    # ==================== live ====================
    def run_live(self, adapters: Optional[Any] = None) -> None:
        """一轮直播检测。"""
        import check_status  # 延迟导入，避免顶层循环依赖 / 启动开销
        from backend.adapters import AdapterRegistry

        cfg_all = self.config_store.get_config()
        persist = LivePersist()
        if adapters is None:
            adapters = AdapterRegistry.from_config(cfg_all)
        logger.info("[DetectionService] 开始直播检测")
        check_status.run_live_check(cfg_all=cfg_all, persist=persist, now=None, adapters=adapters)
        logger.info("[DetectionService] 直播检测完成")

    # ==================== post ====================
    def run_post(self, context: Optional[Any] = None, adapters: Optional[Any] = None) -> None:
        """一轮新作检测（需 Playwright 上下文；context 可由 scheduler 注入复用）。"""
        import check_new_posts
        from backend.adapters import AdapterRegistry

        cfg_all = self.config_store.get_config()
        persist = PostPersist()
        if adapters is None:
            adapters = AdapterRegistry.from_config(cfg_all)
        logger.info("[DetectionService] 开始新作检测")
        check_new_posts.run_post_check(
            cfg_all=cfg_all, persist=persist, now=None, context=context, adapters=adapters
        )
        logger.info("[DetectionService] 新作检测完成")

    # ==================== summary ====================
    def run_summary(self) -> None:
        """一轮摘要投递评估（每轮 live 之后顺带评估）。"""
        import auto_summary

        cfg_all = self.config_store.get_config()
        persist = SummaryPersist()
        logger.info("[DetectionService] 开始摘要投递评估")
        auto_summary.run_summary(cfg_all=cfg_all, persist=persist, now=None)
        logger.info("[DetectionService] 摘要投递评估完成")

    # ==================== transcode ====================
    def run_transcode(self) -> None:
        """一轮封面转存（P1）。"""
        from . import transcode_job

        logger.info("[DetectionService] 开始封面转存")
        transcode_job.run()
        logger.info("[DetectionService] 封面转存完成")
