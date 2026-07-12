"""HistoryStore：统一历史事件写入（替代 log_utils.append_history 的 JSON 版）。

节流逻辑复用 ``log_utils`` 的口径：error / cookie_warn 类事件在 30min 窗口内
同 ``rid+type`` 不重复写入（防刷屏）；其余（info / new_post / system / live_*）始终写入。
落盘目标从 history.json 改为 events_history 表。

注意：这是 DB 版节流，直接查 events_history 表（等价 log_utils.should_suppress 的
磁盘 history.json 判断），不依赖文件。
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from .. import db
from ..models import EventHistory
from ..core.persistence import Persistence

ERROR_THROTTLE_MINUTES: int = 30
_THROTTLE_TYPES = frozenset({"error", "cookie_warn"})


def _parse_time(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None) if ts.tzinfo else ts
    if isinstance(ts, str):
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                return datetime.fromisoformat(ts.replace("Z", "").replace("T", " "))
            except Exception:
                return None
    return None


class HistoryStore:
    """历史事件写入（含 30min 节流）。"""

    def __init__(self, persistence: Optional[Persistence] = None):
        self.persistence = persistence or Persistence()

    def _suppressed(self, rid: str, etype: str, now_str: Optional[str]) -> bool:
        now_dt = _parse_time(now_str) or datetime.utcnow()
        cutoff = now_dt - timedelta(minutes=ERROR_THROTTLE_MINUTES)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        with db.SessionLocal() as s:
            recent = (
                s.query(EventHistory)
                .filter(
                    EventHistory.raw_rid == rid,
                    EventHistory.event_type == etype,
                    EventHistory.occurred_at >= cutoff_str,
                )
                .order_by(EventHistory.id.desc())
                .limit(50)
                .all()
            )
            return len(recent) > 0

    def append_event(self, entry: Dict[str, Any]) -> bool:
        """写一条事件；节流命中返回 False（未写入），否则写入返回 True。"""
        etype = entry.get("type") or entry.get("event_type")
        rid = entry.get("rid") or entry.get("raw_rid")
        if etype in _THROTTLE_TYPES and rid:
            if self._suppressed(rid, etype, entry.get("time") or entry.get("occurred_at")):
                return False
        self.persistence.append_event(entry)
        return True
