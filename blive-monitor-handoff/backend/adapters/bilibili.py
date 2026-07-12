"""BilibiliAdapter：封装既有 fetch_bilibili_batch（零重写检测逻辑）。

复用 check_status.fetch_bilibili_batch（官方 getRoomBaseInfo 批量接口），
实现 fetch_room_status_batch 保持批量效率；单房间回退 fetch_room_status。
live_status 归一化 BOOL；bilibili 的 replay(2) 状态经 extra["raw_live_status"]
透传，保留 replay 推送语义（编排层映射回 "replay"）。
"""

import logging
from typing import Any, Dict, List

import check_status
from backend.adapters.base import PlatformAdapter, RoomModel

logger = logging.getLogger(__name__)

# 复用既有状态码映射（不重写）
BILIBILI_STATUS_MAP = check_status.BILIBILI_STATUS_MAP


class BilibiliAdapter(PlatformAdapter):
    platform = "bilibili"
    supports_live = True
    supports_posts = False
    poll_interval = 300

    def _to_room(self, rid: str, d: Dict[str, Any]) -> RoomModel:
        code = d.get("live_status", 0)
        raw = BILIBILI_STATUS_MAP.get(code, "unknown")
        # status_str 透传原始状态码（含 replay），供编排层映射 Room.live_status 字符串；
        # extra 其余平台专属基线一并并入 meta。
        return RoomModel(
            platform="bilibili",
            room_id=str(rid),
            title=d.get("title", ""),
            live_status=(raw == "live"),
            online=int(d.get("online", 0) or 0),
            area=f"{d.get('parent_area_name', '')}·{d.get('area_name', '')}".strip("·") or "",
            extra={"raw_live_status": raw, "status_str": raw},
        )

    def fetch_room_status_batch(self, room_ids: List[str]) -> Dict[str, RoomModel]:
        ids = [str(r) for r in room_ids]
        # 复用既有纯函数（被测试 monkeypatch 的 check_status.fetch_bilibili_batch）
        data = check_status.fetch_bilibili_batch(ids)
        out: Dict[str, RoomModel] = {}
        for rid in ids:
            d = data.get(rid) or {}
            out[rid] = self._to_room(rid, d)
        return out

    def fetch_room_status(self, room_id: str) -> RoomModel:
        # 单房间回退：经批量接口取单个
        return self.fetch_room_status_batch([room_id])[str(room_id)]

    def fetch_new_posts(self, author_or_room, since=None, baseline=None, context=None):
        # 新作本轮不支持（supports_posts=False）；编排层不会调用，
        # 但显式抛 NotImplementedError 以防误用（同时使类可实例化）。
        raise NotImplementedError("B站仅支持直播检测（supports_posts=False）")
