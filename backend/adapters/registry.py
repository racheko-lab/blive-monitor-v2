"""AdapterRegistry：平台适配器注册表（阶段三 T01 / T04）。

设计 §5.2：内置 bilibili/douyin 常驻（不依赖 config.platforms 段，保证既有监控
不依赖新增配置即可运行）；其余四平台（kuaishou / channels / xhs / taobao_live）按
config.platforms.<code>.enabled 构建。编排层经 ``get(platform)`` 取适配器，实现
「遍历注册表」而非按平台 if/else 内联分支。
"""

import logging
from typing import Any, Dict, Optional

from backend.adapters.base import PlatformAdapter
from backend.adapters.bilibili import BilibiliAdapter
from backend.adapters.channels import ChannelsAdapter
from backend.adapters.douyin import DouyinAdapter
from backend.adapters.kuaishou import KuaishouAdapter
from backend.adapters.taobao_live import TaobaoLiveAdapter
from backend.adapters.xhs import XhsAdapter

logger = logging.getLogger(__name__)

# 平台代码 -> 适配器类（P0 四平台 + 既有 bilibili/douyin 常驻）
_PLATFORM_CLASSES: Dict[str, type] = {
    "kuaishou": KuaishouAdapter,
    "channels": ChannelsAdapter,
    "xhs": XhsAdapter,
    "taobao_live": TaobaoLiveAdapter,
}


class AdapterRegistry:
    """平台适配器注册表。"""

    def __init__(self) -> None:
        #: platform -> PlatformAdapter 实例表
        self._map: Dict[str, PlatformAdapter] = {}

    def register(self, adapter: PlatformAdapter) -> "AdapterRegistry":
        """注册一个适配器实例（覆盖同名）。返回 self 以便链式调用。"""
        if not adapter or not getattr(adapter, "platform", ""):
            logger.warning("跳过无效适配器注册: %r", adapter)
            return self
        self._map[adapter.platform] = adapter
        return self

    def get(self, platform: str) -> Optional[PlatformAdapter]:
        """按平台取适配器；未注册返回 None（编排层据此跳过未知平台）。"""
        return self._map.get(platform)

    def list_platforms(self) -> list:
        """已注册平台代码列表。"""
        return list(self._map.keys())

    @classmethod
    def from_config(cls, cfg_all: Dict) -> "AdapterRegistry":
        """从 BLIVE_CONFIG 构建注册表。

        内置 bilibili/douyin 常驻；``config.platforms`` 段中 enabled=true 的平台
        按凭证/credentials/poll_interval/rate_limit 构建并注册。构建失败的单平台
        被跳过（不阻断其余平台），满足「单平台失败不影响其他」的隔离要求。

        Args:
            cfg_all: BLIVE_CONFIG 完整 dict（可能不含 platforms 段）。
        """
        cfg_all = cfg_all or {}
        reg = cls()
        # 内置常驻（既有 bilibili/douyin 不依赖新增 config 段）
        reg.register(BilibiliAdapter())
        reg.register(DouyinAdapter())

        platforms_cfg = (cfg_all.get("platforms") or {}) if isinstance(cfg_all, dict) else {}
        for code, pcfg in platforms_cfg.items():
            if not isinstance(pcfg, dict):
                continue
            if not pcfg.get("enabled", False):
                continue
            klass = _PLATFORM_CLASSES.get(code)
            if klass is None:
                logger.warning("config.platforms.%s 无对应适配器，跳过", code)
                continue
            try:
                inst = klass(
                    credentials=pcfg.get("credentials", {}) or {},
                    poll_interval=pcfg.get("poll_interval"),
                    rate_limit=pcfg.get("rate_limit"),
                )
                reg.register(inst)
                logger.info("已注册平台适配器: %s", code)
            except Exception as e:  # 单平台构建失败不影响其他平台
                logger.warning("构建适配器 %s 失败，跳过: %s", code, e)
        return reg
