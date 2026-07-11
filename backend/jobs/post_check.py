"""PostPersist：``check_new_posts.run_post_check`` 所需的持久化门面（kind='post'）。"""

from typing import Any, Dict, List, Optional

from ..core.dedup import DedupService
from ..core.history_store import HistoryStore
from ..core.notify_log_store import NotifyLogStore
from ..core.persistence import Persistence


class PostPersist:
    """新作检测持久化门面。"""

    def __init__(self):
        self.persistence = Persistence()
        self.dedup = DedupService()
        self.history = HistoryStore()
        self.notify_log_store = NotifyLogStore()

    def list_rooms(self) -> List[Dict[str, Any]]:
        rooms = self.persistence.list_rooms(kind="post", enabled=None)
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

    def get_tracking(self, platform: str, rid: str) -> Dict[str, Any]:
        return self.persistence.get_tracking(platform, rid, "post")

    def set_room_status(self, **kwargs) -> Any:
        # run_post_check 总是以 kind='post' 调用（kwargs 已含 kind，直接透传）
        return self.persistence.set_room_status(**kwargs)

    def append_event(self, entry: Dict[str, Any]) -> bool:
        return self.history.append_event(entry)

    def dedup_should_notify(self, key: str, cooldown: Optional[float] = None) -> bool:
        cd = cooldown if cooldown is not None else float("inf")
        return self.dedup.should_notify(key, cooldown=cd)

    def dedup_record(self, key: str) -> None:
        self.dedup.record(key)

    def notify_log(self, channel_id, event_type, content_hash, status, target=None) -> Any:
        return self.notify_log_store.log(
            channel_id=channel_id, event_type=event_type,
            content_hash=content_hash, status=status, target=target,
        )
