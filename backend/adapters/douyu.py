"""DouyuAdapter：斗鱼直播（仅直播 ✅，新作 ❌）。

数据源：斗鱼开放平台免鉴权公开接口
    https://open.douyucdn.cn/api/RoomApi/room/{room_id}

实测（2026-10-02，沙箱出口 IP 匿名、无 Cookie）:
    15000   -> {"error":0,"data":{...,"room_status":"0","owner_name":"用户已注销"}}
    36252   -> {"error":0,"data":{...,"room_status":"1","owner_name":"MrGemini",
                "online":5622051,"cate_name":"王者荣耀","start_time":"2026-10-02 13:25:13"}}
    9999    -> {"error":0,"data":{...,"room_status":"1","owner_name":"yyfyyf"}}

边界（异常必须显式报错，不能静默当 offline，否则会污染历史/漏报）:
    /room/0         -> {"error":101,"data":"房间未找到"}
    /room/abc       -> {"error":101,"data":"仅支持房间ID获取房间详情"}
    /room/999999999 -> 纯文本 "Not Found"（非 JSON）

为什么不用 SSR：斗鱼房间页（www.douyu.com/{rid}）的直播态走 WebSocket/长轮询，
SSR HTML 里没有可靠状态位；而 open.douyucdn.cn 是官方公开的 CDN 接口，
匿名可用、响应小（gift 数组虽大但可截断）、无需 Cookie，是本仓库最省心的平台。

字段映射:
    data.room_name  -> RoomModel.title        （直播间标题）
    data.owner_name -> RoomModel.name         （主播昵称）
    data.room_status == "1" -> live_status=True
    data.online     -> RoomModel.online       （人气值，斗鱼为加权热度非真实人数）
    data.cate_name  -> RoomModel.area         （分区）
    data.avatar     -> RoomModel.avatar
    data.room_thumb -> RoomModel.cover
    url = https://www.douyu.com/{room_id}
"""

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from common import DEFAULT_USER_AGENT
from backend.adapters.base import PlatformAdapter, RoomModel, AdapterError

logger = logging.getLogger(__name__)

#: 房间详情接口（免鉴权，公开 CDN）
ROOM_API = "https://open.douyucdn.cn/api/RoomApi/room/{room_id}"

#: room_status 语义（实测）：0=未开播，1=直播中，2=轮播/回放。
#:
#: 2026-10-03 实测到 "2"：房间 36252 前半场是 "1"（online 562 万），后半场变 "2"
#: （online=0、room_name 保留、start_time 未变）—— 即下播后的轮播/回放态。
#:
#: 当前只把 "1" 判为 live，"2" 与 "0" 一并归为 offline。这是刻意的保守选择：
#: 开播检测只依赖 0/2 → 1 的跃迁，把 "2" 当 offline 不影响开播漏报；
#: 反之若把 "2" 误判为 live，会在主播已下播时持续误报。原值存 extra 供后续精细化。
STATUS_LIVE = "1"

#: 房间「靓号」解析页。斗鱼给主播分配短号（如 15000），访问 m.douyu.com/{靓号}
#: 会渲染出真实房间的直播间。SSR 里同时存在两个字段：
#:     "roomId":"15000"   <- 照抄 URL，即靓号本身
#:     "rid":796449       <- 真实房间号
#: 必须取 "rid"。
PRETTY_ID_PAGE = "https://m.douyu.com/{room_id}"
RE_PAGE_RID = re.compile(r'"rid"\s*:\s*"?(\d+)')

#: 靓号在 RoomApi 上的「占位壳」特征：公开接口只认真实房间 ID，
#: 传靓号会返回一个已注销样式的空壳（不是该靓号真的注销了）。
PLACEHOLDER_OWNER_NAME = "用户已注销"
PLACEHOLDER_START_PREFIX = "1970-01-01"

UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


class DouyuAdapter(PlatformAdapter):
    """斗鱼直播适配器（仅直播）。"""

    platform = "douyu"
    supports_live = True
    supports_posts = False  # 斗鱼无「新作品」形态，本轮不做
    poll_interval = 60
    rate_limit = {"max_requests": 60, "window_sec": 60, "backoff_sec": 5}
    needs_context = False

    def __init__(self, credentials: Optional[Dict[str, Any]] = None,
                 poll_interval: Optional[int] = None,
                 rate_limit: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(credentials or {}, poll_interval, rate_limit)

    def _http_get_json(self, url: str, timeout: int = 10) -> Dict[str, Any]:
        """GET + JSON 解析。非 JSON / HTTP 错误一律抛 AdapterError（不静默降级）。"""
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": "https://www.douyu.com/",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise AdapterError(f"斗鱼接口 HTTP {e.code}") from e
        except Exception as e:  # noqa: BLE001  # 网络层异常统一归一
            raise AdapterError(f"斗鱼接口请求失败: {e}") from e
        try:
            obj = json.loads(raw)
        except Exception as e:  # noqa: BLE001  # 例如超大房间号返回纯文本 "Not Found"
            raise AdapterError(f"斗鱼接口返回非 JSON: {raw[:40]}") from e
        if not isinstance(obj, dict):
            raise AdapterError(f"斗鱼接口返回结构异常: {type(obj).__name__}")
        return obj

    @staticmethod
    def _looks_like_pretty_id_placeholder(data: Any) -> bool:
        """判断 RoomApi 返回的是不是「靓号占位壳」。

        斗鱼公开接口只认**真实房间 ID**。传靓号（如 15000）不会报错，而是返回一个
        已注销样式的空壳：`owner_name="用户已注销"`、`room_name="用户已注销的直播间 15000"`、
        `start_time="1970-01-01 08:00:00"`、默认头像。看到这些特征就要走靓号解析，
        否则会把一个正在直播的房间误判成废号。
        """
        d = data if isinstance(data, dict) else {}
        return (
            str(d.get("owner_name") or "") == PLACEHOLDER_OWNER_NAME
            or str(d.get("start_time") or "").startswith(PLACEHOLDER_START_PREFIX)
        )

    def _resolve_pretty_id(self, pretty_id: str, timeout: int = 10) -> Optional[str]:
        """靓号 → 真实房间号：抓 m.douyu.com/{靓号} 页面，取 SSR 里的 `"rid"`。

        与 ``tools/douyu_resolve.py`` 同源（该脚本是给人用的 CLI 版本）。
        返回 None 表示页面没解析到（网络失败 / 该号确实没有映射）。
        """
        try:
            req = urllib.request.Request(
                PRETTY_ID_PAGE.format(room_id=pretty_id),
                headers={"User-Agent": UA_MOBILE, "Accept": "text/html"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                html = r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            logger.warning("[douyu] 靓号 %s 页面抓取失败: %s", pretty_id, e)
            return None
        m = RE_PAGE_RID.search(html)
        return m.group(1) if m else None

    def _fetch_room_data(self, room_id: str) -> Dict[str, Any]:
        """取并校验 RoomApi 的 data 段（失败一律抛 AdapterError）。"""
        obj = self._http_get_json(ROOM_API.format(room_id=room_id))
        if obj.get("error") not in (0, "0"):
            raise AdapterError(f"斗鱼房间不可用: error={obj.get('error')} {obj.get('data')}")
        data = obj.get("data")
        if not isinstance(data, dict) or not data:
            raise AdapterError(f"斗鱼房间 {room_id} 无数据")
        return data

    @staticmethod
    def _room_from_data(requested_id: str, data: Dict[str, Any],
                        resolved_id: Optional[str] = None) -> RoomModel:
        """data → RoomModel。``room_id`` 保留**请求时用的号**（可能是靓号），
        真实房间号放 ``extra.resolved_room_id`` —— 这样生成的直播间 URL 用靓号，
        点进去由斗鱼自动跳转，符合用户直觉。"""
        status_raw = str(data.get("room_status") or "")
        extra = {
            "room_status_raw": status_raw,
            "start_time": str(data.get("start_time") or ""),
            "source": "open.douyucdn.cn/RoomApi",
        }
        if resolved_id:
            extra["resolved_room_id"] = resolved_id
            extra["is_pretty_id"] = True
        return RoomModel(
            platform="douyu",
            room_id=requested_id,
            name=str(data.get("owner_name") or ""),
            title=str(data.get("room_name") or ""),
            live_status=(status_raw == STATUS_LIVE),
            url=f"https://www.douyu.com/{requested_id}",
            cover=str(data.get("room_thumb") or ""),
            avatar=str(data.get("avatar") or ""),
            online=int(data.get("online") or 0),
            area=str(data.get("cate_name") or ""),
            extra=extra,
        )

    def fetch_room_status(self, room_id: str) -> RoomModel:
        """查询单个斗鱼房间直播态（**自动支持靓号**）。

        主路径走 RoomApi；若返回「已注销占位壳」，判定为靓号，抓页面解析出真实
        房间号后重查一次。房间号可以是真实 ID（如 796449）也可以是靓号（如 15000）。

        Raises:
            AdapterError: 房间不存在 / 房间号非法 / 接口不可达 / 靓号解析失败。
                编排层（check_status.fetch_douyu）会捕获并转为 status="error"，
                与 bili/douyin/kuaishou 一致，不会静默当 offline。
        """
        room_id = str(room_id).strip()
        if not room_id.isdigit():
            raise AdapterError(f"斗鱼房间号必须为纯数字: {room_id!r}")

        data = self._fetch_room_data(room_id)
        if self._looks_like_pretty_id_placeholder(data):
            real_id = self._resolve_pretty_id(room_id)
            if not real_id or real_id == room_id:
                raise AdapterError(
                    f"斗鱼房间 {room_id} 不可用（已注销，且靓号解析无结果）"
                )
            logger.info("[douyu] 靓号 %s 解析为真实房间 %s", room_id, real_id)
            data = self._fetch_room_data(real_id)
            return self._room_from_data(room_id, data, resolved_id=real_id)

        return self._room_from_data(room_id, data)

    def fetch_room_status_batch(self, room_ids: List[str]) -> Dict[str, RoomModel]:
        """批量查询（默认逐个串行；斗鱼公开接口无真批量端点）。

        单房失败不影响其余房间——失败项不进返回 dict，由编排层按「无数据」处理。
        """
        out: Dict[str, RoomModel] = {}
        for rid in room_ids or []:
            try:
                out[str(rid)] = self.fetch_room_status(rid)
            except Exception as e:  # noqa: BLE001
                logger.warning("[douyu] 房间 %s 查询失败（跳过）: %s", rid, e)
        return out

    def fetch_new_posts(self, author_or_room: str, since: Optional[Any] = None,
                        baseline: Optional[Dict[str, Any]] = None,
                        context: Any = None) -> List[Any]:
        # 斗鱼无「新作品」形态（supports_posts=False）；编排层不会调用，
        # 但显式抛 NotImplementedError 以防误用。
        raise NotImplementedError("斗鱼仅支持直播检测（supports_posts=False）")
