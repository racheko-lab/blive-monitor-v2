"""SummaryPersist：``auto_summary.run_summary`` 所需的持久化门面。"""

from typing import Any, Dict, List, Optional

from ..config_store import ConfigStore
from ..core.persistence import Persistence


class SummaryPersist:
    """摘要投递持久化门面。"""

    def __init__(self):
        self.config_store = ConfigStore()
        self.persistence = Persistence()

    def get_summary_state(self) -> Dict[str, Any]:
        return self.config_store.get_summary_state()

    def set_summary_state(self, data: Dict[str, Any], remove: Optional[list] = None) -> Dict[str, Any]:
        return self.config_store.put_summary_state(data, remove=remove)

    def get_events(self) -> List[Dict[str, Any]]:
        """取最近历史事件，映射为 ``compute_summary`` 兼容的 dict 列表。

        字段：time / type / rid / account / name / platform。
        """
        events = self.persistence.list_events(limit=2000)
        out: List[Dict[str, Any]] = []
        for e in events:
            out.append({
                "time": e.occurred_at,
                "type": e.event_type,
                "status": e.event_type,
                "rid": e.raw_rid,
                "account": e.account,
                "name": e.name,
                "platform": e.platform,
            })
        return out
