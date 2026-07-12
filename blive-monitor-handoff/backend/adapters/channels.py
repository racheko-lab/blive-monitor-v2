"""ChannelsAdapter：微信视频号直播 + 新作（阶段三 T02）。

访问成本高（见 docs/phase3_design.md §4.2）：
- mode=open_platform（默认/首选）：需视频号助手/微信开放平台认证凭证
  （app_id/app_secret/access_token）。缺凭证时 fetch 抛 AdapterGated（编排层记
  system/cookie_warn，不推送）。
- mode=playwright：用已登录微信 Web Cookie 起 Playwright 渲染视频号页抓 liveStatus/DOM。

⚠️ 此处需真实凭证/API 接入：开放平台凭证 或 稳定的登录态 Cookie。
两种路径均为「结构 + 优雅降级」，真实接口待接入。
"""

import logging
from typing import Any, Dict, List, Optional

from backend.adapters.base import (
    AdapterGated,
    AdapterSkip,
    PlatformAdapter,
    PostModel,
    RoomModel,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODE = "open_platform"


class ChannelsAdapter(PlatformAdapter):
    platform = "channels"
    supports_live = True
    supports_posts = True
    poll_interval = 600
    rate_limit = {"max_requests": 10, "window_sec": 60, "backoff_sec": 60}
    needs_context = True  # playwright 登录态路径需要无头浏览器

    def __init__(self, credentials: Optional[Dict[str, Any]] = None,
                 poll_interval: Optional[int] = None,
                 rate_limit: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(credentials or {}, poll_interval, rate_limit)
        self.mode = str(self.credentials.get("mode") or _DEFAULT_MODE)
        self.app_id = self.credentials.get("app_id") or ""
        self.app_secret = self.credentials.get("app_secret") or ""
        self.access_token = self.credentials.get("access_token") or ""
        self.cookie = self.credentials.get("cookie") or ""

    def apply_credentials(self, context: Any) -> None:
        """把登录 Cookie 注入 Playwright 上下文（playwright 模式用）。"""
        if self.cookie and context is not None:
            try:
                context.add_cookies([{
                    "name": "session",
                    "value": self.cookie,
                    "domain": ".weixin.qq.com",
                    "path": "/",
                }])
            except Exception as e:  # noqa: BLE001
                logger.warning("[channels] 注入 Cookie 失败: %s", e)

    def _has_open_platform_creds(self) -> bool:
        return bool(self.app_id and self.access_token)

    def fetch_room_status(self, room_id: str) -> RoomModel:
        room_id = str(room_id)
        if self.mode == "open_platform":
            if not self._has_open_platform_creds():
                # ⚠️ 此处需真实凭证/API 接入：开放平台认证 app_id/access_token
                raise AdapterGated(detail="视频号开放平台需 app_id/access_token 凭证")
            # 真实接口骨架（需 access_token）：调用官方「获取直播状态」。
            # ⚠️ 待接入真实 endpoint（微信开放平台「直播间状态」接口）。
            raise AdapterGated(detail="视频号开放平台直播接口待接入（需 access_token）")
        # mode == playwright：由运行环境注入 context 渲染抓 DOM
        raise AdapterSkip(
            "playwright_required",
            detail="视频号 playwright 模式需注入 BrowserContext",
        )

    def fetch_new_posts(self, author_or_room: str, since: Optional[Any] = None,
                        baseline: Optional[Dict[str, Any]] = None,
                        context: Any = None) -> List[PostModel]:
        if self.mode == "open_platform":
            if not self._has_open_platform_creds():
                raise AdapterGated(detail="视频号开放平台需 app_id/access_token 凭证")
            raise AdapterGated(detail="视频号开放平台新作接口待接入（需 access_token）")
        raise AdapterSkip(
            "playwright_required",
            detail="视频号 playwright 模式需注入 BrowserContext",
        )
