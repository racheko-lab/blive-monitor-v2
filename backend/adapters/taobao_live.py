"""TaobaoLiveAdapter：淘宝直播（阶段三 T02）。

仅直播 ✅，新作 ❌ 本轮不做（docs/phase3_design.md §4.4）。
- supports_posts = False：编排层对 kind='post' 的 taobao 房间直接跳过
  （fetch_new_posts 显式抛 NotImplementedError，防误用）。
- 直播：主路径 SSR（live.taobao.com/room/{id} 解析 __INITIAL_STATE__/liveStatus）；
  降级 Playwright 抓 mtop/live API。
  ⚠️ 此处需真实凭证/API 接入：正常 UA + 有效登录 Cookie（淘宝反爬严）。
  当前为「结构 + 优雅降级」：抓取失败返回 offline，不抛未捕获异常。
"""

import json
import logging
import re
import urllib.request
from typing import Any, Dict, List, Optional

from backend.adapters.base import PlatformAdapter, RoomModel

logger = logging.getLogger(__name__)

_TAOBAO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class TaobaoLiveAdapter(PlatformAdapter):
    platform = "taobao_live"
    supports_live = True
    supports_posts = False  # 仅直播
    poll_interval = 300
    rate_limit = {"max_requests": 15, "window_sec": 60, "backoff_sec": 30}
    needs_context = False

    def __init__(self, credentials: Optional[Dict[str, Any]] = None,
                 poll_interval: Optional[int] = None,
                 rate_limit: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(credentials or {}, poll_interval, rate_limit)
        self.cookie = str(self.credentials.get("cookie") or "")

    def _http_get(self, url: str, timeout: int = 10) -> bytes:
        hdr = {"User-Agent": _TAOBAO_UA, "Referer": "https://live.taobao.com/"}
        if self.cookie:
            hdr["Cookie"] = self.cookie
        req = urllib.request.Request(url, headers=hdr)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def fetch_room_status(self, room_id: str) -> RoomModel:
        room_id = str(room_id)
        try:
            # 主：SSR 解析 liveStatus
            # ⚠️ 此处需真实凭证/API 接入：正常 UA + 有效登录 Cookie（淘宝反爬严）
            html = self._http_get(
                f"https://live.taobao.com/room/{room_id}"
            ).decode("utf-8", "replace")
            return self._room_from_html(room_id, html)
        except Exception as e:  # noqa: BLE001
            logger.warning("[taobao_live] live fetch failed (degrade to offline): %s", e)
            return RoomModel(
                platform="taobao_live", room_id=room_id, live_status=False,
                extra={"degraded": True},
            )

    @staticmethod
    def _room_from_html(room_id: str, html: str) -> RoomModel:
        """SSR 解析 __INITIAL_STATE__ / window.__INIT_DATA__ 的 liveStatus（纯函数）。"""
        for pat in (
            r"window\.__INITIAL_STATE__\s*=\s*({.*?});",
            r"window\.__INIT_DATA__\s*=\s*({.*?});",
        ):
            m = re.search(pat, html, re.S)
            if not m:
                continue
            try:
                state = json.loads(m.group(1))
            except Exception:  # noqa: BLE001
                continue
            node = state.get("liveRoom") or state.get("room") or {}
            live_status = node.get("liveStatus")
            living = live_status in (1, "1", True, "true")
            return RoomModel(
                platform="taobao_live",
                room_id=room_id,
                title=node.get("title") or "",
                live_status=living,
                online=int(node.get("onlineCount", 0) or 0),
                cover=node.get("coverUrl") or "",
                extra={"live_status_raw": live_status, "source": "ssr"},
            )
        return RoomModel(platform="taobao_live", room_id=room_id, live_status=False)

    def fetch_new_posts(self, author_or_room: str, since: Optional[Any] = None,
                        baseline: Optional[Dict[str, Any]] = None,
                        context: Any = None) -> List[Any]:
        # 新作本轮不支持（supports_posts=False）；编排层不会调用，
        # 但显式抛 NotImplementedError 以防误用。
        raise NotImplementedError("淘宝直播仅支持直播检测（supports_posts=False）")
