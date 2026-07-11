"""KuaishouAdapter：快手直播 + 新作（阶段三 T02）。

直播：主路径 live_api（带 did）+ 降级 SSR（window.__INITIAL_STATE__）。
新作：visionProfilePhotoList graphql（带 did/client_key/cookie）+ 基线比较。

所有网络抓取经异常兜底，失败优雅降级为 offline / 无新作（绝不抛未捕获异常中断整轮）。

⚠️ 此处需真实凭证/API 接入：live_api / graphql 需有效 did（匿名可生成）或登录 Cookie；
数据中心 IP / 缺 Cookie 易触发风控，生产环境请按 docs/phase3_design.md §4.1 配置 credentials。
"""

import json
import logging
import re
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.adapters.base import AdapterGated, PlatformAdapter, PostModel, RoomModel

logger = logging.getLogger(__name__)

_KUAISHOU_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_DEFAULT_CLIENT_KEY = "3c7cd4d734b53483"


def _to_ts(v: Any) -> Optional[int]:
    """尽力把时间值转成 epoch 秒（兼容 int / 字符串）。"""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _ts_to_bj(ts: Optional[int]) -> str:
    """epoch 秒 -> 北京时间字符串；失败返回空串。"""
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


class KuaishouAdapter(PlatformAdapter):
    platform = "kuaishou"
    supports_live = True
    supports_posts = True
    poll_interval = 300
    rate_limit = {"max_requests": 20, "window_sec": 60, "backoff_sec": 30}
    needs_context = False  # SSR 主路径无需浏览器；Playwright 降级留作 P2 增强

    def __init__(self, credentials: Optional[Dict[str, Any]] = None,
                 poll_interval: Optional[int] = None,
                 rate_limit: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(credentials or {}, poll_interval, rate_limit)
        self.did = str(self.credentials.get("did") or "")
        self.client_key = str(self.credentials.get("client_key") or _DEFAULT_CLIENT_KEY)
        self.cookie = str(self.credentials.get("cookie") or "")

    # ---- 网络（可被测试 monkeypatch）----
    def _http_get(self, url: str, headers: Optional[Dict[str, str]] = None,
                  timeout: int = 10) -> bytes:
        hdr = {"User-Agent": _KUAISHOU_UA, "Referer": "https://live.kuaishou.com/"}
        if self.cookie:
            hdr["Cookie"] = self.cookie
        if headers:
            hdr.update(headers)
        req = urllib.request.Request(url, headers=hdr)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    # ---------- 直播 ----------
    def fetch_room_status(self, room_id: str) -> RoomModel:
        room_id = str(room_id)
        try:
            # 主：直播 API（需 did；无登录可匿名，但风控下返回空）
            # ⚠️ 此处需真实凭证/API 接入：principalId + did
            api = (
                "https://live.kuaishou.com/live_api/liveroom/liveroomDetail"
                f"?principalId={room_id}"
            )
            hdr = {"Cookie": f"did={self.did}"} if self.did else {}
            raw = self._http_get(api, hdr)
            d = json.loads(raw)
            data = d.get("data") or {}
            info = data.get("liveStreamInfo") or {}
            living = bool(data.get("living") or info.get("living", False))
            return RoomModel(
                platform="kuaishou",
                room_id=room_id,
                title=data.get("caption") or "",
                live_status=living,
                online=int(info.get("watcherCount", 0) or 0),
                cover=info.get("coverUrl") or "",
                extra={"living": living, "source": "live_api"},
            )
        except Exception as e:  # noqa: BLE001
            # 降级：SSR 解析主页 __INITIAL_STATE__
            try:
                html = self._http_get(
                    f"https://live.kuaishou.com/u/{room_id}", timeout=10
                ).decode("utf-8", "replace")
                return self._room_from_html(room_id, html)
            except Exception as e2:  # noqa: BLE001
                logger.warning(
                    "[kuaishou] live fetch failed (degrade to offline): %s | %s", e, e2
                )
                return RoomModel(
                    platform="kuaishou", room_id=room_id, live_status=False,
                    extra={"degraded": True},
                )

    @staticmethod
    def _room_from_html(room_id: str, html: str) -> RoomModel:
        """SSR 解析 window.__INITIAL_STATE__（纯函数，便于单测）。"""
        m = re.search(
            r"window\.__INITIAL_STATE__\s*=\s*({.*?});?\s*(?:</script>|$)", html, re.S
        )
        if not m:
            return RoomModel(platform="kuaishou", room_id=room_id, live_status=False)
        try:
            state = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            return RoomModel(platform="kuaishou", room_id=room_id, live_status=False)
        live = state.get("liveroom") or {}
        living = bool(live.get("living", False))
        return RoomModel(
            platform="kuaishou",
            room_id=room_id,
            title=live.get("caption") or "",
            live_status=living,
            online=int(live.get("watcherCount", 0) or 0),
            cover=live.get("coverUrl") or "",
            extra={"living": living, "source": "ssr"},
        )

    # ---------- 新作 ----------
    def fetch_new_posts(self, author_or_room: str, since: Optional[datetime] = None,
                        baseline: Optional[Dict[str, Any]] = None,
                        context: Any = None) -> List[PostModel]:
        rid = str(author_or_room)
        t = baseline if isinstance(baseline, dict) else {}
        try:
            # 主：visionProfilePhotoList graphql（需 did/client_key/cookie）
            # ⚠️ 此处需真实凭证/API 接入：graphql 签名 + 登录态；风控下返回空
            posts = self._fetch_graphql_photos(rid)
        except AdapterGated:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("[kuaishou] 新作接口失败（降级为空）: %s", e)
            raise AdapterGated(detail="快手作品接口需 did/登录 Cookie，当前被风控")

        out: List[PostModel] = []
        prev_id = t.get("latest_post_id", "")
        prev_ts = _to_ts(t.get("latest_published_at"))
        for p in posts:
            pid = p.get("photoId", "")
            ts = _to_ts(p.get("timestamp"))
            # 仅返回「比基线新」的作品（id 不同且时间更新；无时间则仅按 id 去重）
            if pid and pid != prev_id and (prev_ts is None or ts is None or ts > prev_ts):
                is_image = bool(p.get("is_image", False))
                out.append(PostModel(
                    platform="kuaishou",
                    post_id=pid,
                    author=t.get("nickname", "") or p.get("author", ""),
                    url=p.get("url", ""),
                    cover=p.get("coverUrl", ""),
                    published_at=_ts_to_bj(ts),
                    title=p.get("caption", ""),
                    extra={
                        "conf": "api",
                        "type": "图文" if is_image else "视频",
                        "dedup_key": f"post:kuaishou:{pid}",
                    },
                ))
        # 更新基线（取最新一条）
        if posts:
            last = max(posts, key=lambda x: _to_ts(x.get("timestamp")) or 0)
            t["latest_post_id"] = last.get("photoId", "")
            t["latest_published_at"] = _ts_to_bj(_to_ts(last.get("timestamp")))
        return out

    def _fetch_graphql_photos(self, rid: str) -> List[Dict[str, Any]]:
        """调用 visionProfilePhotoList（需 did/client_key/cookie）。

        ⚠️ 此处需真实凭证/API 接入：graphql 端点 + 签名/登录态。
        当前为请求骨架，真实实现需构造 graphql body 并带 client_key/did。
        """
        url = "https://www.kuaishou.com/graphql"
        body = json.dumps({
            "operationName": "visionProfilePhotoList",
            "variables": {"userId": rid, "page": 1},
            "query": (
                "query visionProfilePhotoList($userId:String,$page:Int){"
                "visionProfilePhotoList(userId:$userId,page:$page){photoId caption "
                "coverUrl url timestamp is_image}}"
            ),
        }).encode("utf-8")
        hdr = {"Content-Type": "application/json",
               "Referer": "https://www.kuaishou.com/"}
        if self.did:
            hdr["Cookie"] = f"did={self.did}; client_key={self.client_key}"
        req = urllib.request.Request(url, data=body, headers=hdr, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        feeds = ((d.get("data") or {}).get("visionProfilePhotoList") or {}).get("feeds") or []
        return feeds
