"""XhsAdapter：小红书（阶段三 T02）。

仅新作/笔记 ✅，直播 ❌ 本轮不做（docs/phase3_design.md §4.3）。
- supports_live = False：编排层对 kind='live' 的 xhs 房间直接跳过
  （fetch_room_status 显式抛 NotImplementedError，防误用）。
- 新作：主路径签名 API（x-s/x-t + 有效登录 Cookie）；降级 Playwright 拦 user_posted XHR。
  ⚠️ 此处需真实凭证/API 接入：登录 Cookie + 签名器（xhspro 等）生成 x-s/x-t。
  当前为「结构 + 优雅降级」：接口缺凭证时抛 AdapterGated（编排层记 cookie_warn）。
"""

import logging
from typing import Any, Dict, List, Optional

from backend.adapters.base import AdapterGated, PlatformAdapter, PostModel, RoomModel

logger = logging.getLogger(__name__)

_DEFAULT_MODE = "notes_only"


class XhsAdapter(PlatformAdapter):
    platform = "xhs"
    supports_live = False  # 仅新作
    supports_posts = True
    poll_interval = 900
    rate_limit = {"max_requests": 8, "window_sec": 60, "backoff_sec": 120}
    needs_context = True  # 签名 API 或 Playwright 拦 XHR

    def __init__(self, credentials: Optional[Dict[str, Any]] = None,
                 poll_interval: Optional[int] = None,
                 rate_limit: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(credentials or {}, poll_interval, rate_limit)
        self.mode = str(self.credentials.get("mode") or _DEFAULT_MODE)
        self.cookie = self.credentials.get("cookie") or ""
        self.signer = self.credentials.get("signer") or "xhspro"

    def fetch_room_status(self, room_id: str) -> RoomModel:
        # 直播本轮不支持（supports_live=False）；编排层不会调用，
        # 但显式抛 NotImplementedError 以防误用。
        raise NotImplementedError("小红书直播检测本轮未支持（supports_live=False）")

    def fetch_new_posts(self, author_or_room: str, since: Optional[Any] = None,
                        baseline: Optional[Dict[str, Any]] = None,
                        context: Any = None) -> List[PostModel]:
        rid = str(author_or_room)
        t = baseline if isinstance(baseline, dict) else {}
        try:
            notes = self._fetch_notes(rid)
        except AdapterGated:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("[xhs] 新作接口失败（降级/需凭证）: %s", e)
            raise AdapterGated(detail="小红书笔记接口需登录 Cookie+签名，当前被风控")

        out: List[PostModel] = []
        prev_id = t.get("latest_post_id", "")
        for n in notes:
            nid = n.get("id", "")
            if not nid or nid == prev_id:
                continue
            cover = n.get("cover")
            if isinstance(cover, dict):
                cover = (cover.get("url") or [""])[0] if isinstance(cover.get("url"), list) else cover.get("url", "")
            out.append(PostModel(
                platform="xhs",
                post_id=nid,
                author=t.get("name", "") or n.get("author", ""),
                url=n.get("url", ""),
                cover=cover or "",
                published_at=str(n.get("time", "")),
                title=n.get("title") or n.get("desc") or "",
                extra={
                    "conf": "api",
                    "type": n.get("type", "笔记"),
                    "dedup_key": f"post:xhs:{nid}",
                },
            ))
        if notes:
            t["latest_post_id"] = notes[0].get("id", "")
        return out

    def _fetch_notes(self, rid: str) -> List[Dict[str, Any]]:
        """调用 edith.xiaohuoshu.com/api/sns/web/v1/user_posted。

        ⚠️ 此处需真实凭证/API 接入：必须带 x-s/x-t/x-bogus 签名（签名器生成）
        + 有效登录 Cookie；数据中心 IP 触发风控。当前为结构骨架，真实实现需注入签名头。
        """
        raise AdapterGated(detail="小红书签名 API 待接入（需 Cookie + x-s/x-t 签名器）")
