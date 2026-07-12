"""DedupService：通知去重账本（替代 notify_dedup.json，落 notify_dedup 表）。

语义与 notify_dedup.py 完全一致（设计 §7.4）：
  - 直播 key ``live:{platform}_{rid}``：冷却 2h（吸收闪烁 / 状态丢失）。
  - 新作品 key ``post:{sec_uid}:{aweme_id}``：永久（传 cooldown=math.inf）。
  - live: key 超过 7d 裁剪；post: 永久保留；超过 5000 条保留最近 N。
  - ``record`` 仅在推送成功后调用，避免「标记去重却推送失败」导致漏报。
"""

import math
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from .. import db
from ..models import NotifyDedup

LIVE_COOLDOWN_SECONDS: int = 7200
PERMANENT = math.inf
LIVE_KEY_TTL_SECONDS: int = 7 * 24 * 3600
MAX_ENTRIES: int = 5000


class DedupService:
    """去重账本服务（DB 版）。"""

    @contextmanager
    def _session_scope(self):
        s: Session = db.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def should_notify(
        self, key: str, cooldown: float = LIVE_COOLDOWN_SECONDS, now: Optional[float] = None
    ) -> bool:
        if not key:
            return True
        now = now if now is not None else time.time()
        with self._session_scope() as s:
            entry = s.get(NotifyDedup, key)
            if not entry:
                return True
            last_ts = entry.last_sent_at or 0.0
            return (now - last_ts) >= cooldown

    def record(self, key: str, now: Optional[float] = None, meta: Optional[Dict[str, Any]] = None) -> None:
        if not key:
            return
        now = now if now is not None else time.time()
        with db.WRITER_LOCK:
            with self._session_scope() as s:
                entry = s.get(NotifyDedup, key)
                if entry is None:
                    entry = NotifyDedup(key=key, last_sent_at=now, meta=meta or {})
                    s.add(entry)
                else:
                    entry.last_sent_at = now
                    if meta:
                        base = dict(entry.meta or {})
                        base.update(meta)
                        entry.meta = base

    def last_sent_at(self, key: str) -> float:
        """查询某 key 最近一次发送时间戳（不存在返回 0.0）。"""
        with self._session_scope() as s:
            row = s.get(NotifyDedup, key)
            return float(row.last_sent_at) if row else 0.0

    def prune(self, now: Optional[float] = None) -> None:
        now = now if now is not None else time.time()
        with db.WRITER_LOCK:
            with self._session_scope() as s:
                rows = s.query(NotifyDedup).all()
                if not rows:
                    return
                kept: Dict[str, NotifyDedup] = {}
                for e in rows:
                    if str(e.key).startswith("live:"):
                        if (now - (e.last_sent_at or 0.0)) < LIVE_KEY_TTL_SECONDS:
                            kept[e.key] = e
                    else:
                        kept[e.key] = e
                if len(kept) > MAX_ENTRIES:
                    items = sorted(kept.values(), key=lambda x: x.last_sent_at or 0.0)
                    kept = {x.key: x for x in items[-MAX_ENTRIES:]}
                # 删除被裁掉的键
                drop = [e for e in rows if e.key not in kept]
                for e in drop:
                    s.delete(e)
