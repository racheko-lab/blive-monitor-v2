"""LivePersist：``check_status.run_live_check`` 所需的持久化门面（kind='live'）。

把所有 DB 写操作收敛到 Persistence / DedupService / HistoryStore / NotifyLogStore，
使 ``check_status`` 与 SQLAlchemy 完全解耦（check_status 仅依赖纯函数 + 本门面的 duck-typed 接口）。
"""

from typing import Any, Dict, List, Optional

from .. import config
from ..core.dedup import DedupService
from ..core.history_store import HistoryStore
from ..core.notify_log_store import NotifyLogStore
from ..core.persistence import Persistence


class LivePersist:
    """直播检测持久化门面。"""

    def __init__(self):
        self.persistence = Persistence()
        self.dedup = DedupService()
        self.history = HistoryStore()
        self.notify_log_store = NotifyLogStore()

    # ---------- Room 列表 / 状态 / 基线 ----------
    def list_rooms(self) -> List[Dict[str, Any]]:
        rooms = self.persistence.list_rooms(kind="live", enabled=None)
        return [
            {
                "platform": r.platform,
                "external_id": r.external_id,
                "name": r.name,
                "enabled": r.enabled,
                "tags": r.tags,
                "meta": r.meta or {},
            }
            for r in rooms
        ]

    def get_prev_status(self, platform: str, rid: str) -> Optional[str]:
        return self.persistence.get_room_status(platform, rid, "live")

    def get_tracking(self, platform: str, rid: str) -> Dict[str, Any]:
        return self.persistence.get_tracking(platform, rid, "live")

    def set_room_status(self, **kwargs) -> Any:
        # run_live_check 已带 kind='live'，直接透传避免重复关键字参数。
        return self.persistence.set_room_status(**kwargs)

    # ---------- 历史 / 去重 / 通知账本 ----------
    def append_event(self, entry: Dict[str, Any]) -> bool:
        return self.history.append_event(entry)

    def dedup_should_notify(self, key: str, cooldown: Optional[float] = None) -> bool:
        cd = config.LIVE_DEDUP_COOLDOWN_SEC if cooldown is None else cooldown
        return self.dedup.should_notify(key, cooldown=cd)

    def dedup_record(self, key: str) -> None:
        self.dedup.record(key)

    def notify_log(self, channel_id, event_type, content_hash, status, target=None) -> Any:
        return self.notify_log_store.log(
            channel_id=channel_id, event_type=event_type,
            content_hash=content_hash, status=status, target=target,
        )
