"""NotifyLogStore：每次推送尝试落 notify_log（成功/失败均记录）。"""

from contextlib import contextmanager
from typing import Optional

from sqlalchemy.orm import Session

from .. import db
from ..models import NotifyLog


class NotifyLogStore:
    """通知账本写入。"""

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

    def log(
        self,
        channel_id: Optional[str],
        event_type: Optional[str],
        content_hash: Optional[str],
        status: str,
        target: Optional[str] = None,
        sent_at: Optional[str] = None,
    ) -> NotifyLog:
        from .. import config

        sent_at = sent_at or _now_str()
        with db.WRITER_LOCK:
            with self._session_scope() as s:
                rec = NotifyLog(
                    channel_id=channel_id,
                    event_type=event_type,
                    target=target,
                    content_hash=content_hash,
                    sent_at=sent_at,
                    status=status,
                )
                s.add(rec)
                s.flush()
                # 返回 detached 副本
                return NotifyLog(
                    id=rec.id,
                    channel_id=rec.channel_id,
                    event_type=rec.event_type,
                    target=rec.target,
                    content_hash=rec.content_hash,
                    sent_at=rec.sent_at,
                    status=rec.status,
                )

    def list_logs(
        self,
        limit: int = 200,
        offset: int = 0,
        channel_id: Optional[str] = None,
        event_type: Optional[str] = None,
        status: Optional[str] = None,
    ):
        with self._session_scope() as s:
            qry = s.query(NotifyLog)
            if channel_id is not None:
                qry = qry.filter(NotifyLog.channel_id == channel_id)
            if event_type is not None:
                qry = qry.filter(NotifyLog.event_type == event_type)
            if status is not None:
                qry = qry.filter(NotifyLog.status == status)
            qry = qry.order_by(NotifyLog.id.desc()).limit(limit).offset(offset)
            return qry.all()


def _now_str() -> str:
    from common import bjnow

    return bjnow().strftime("%Y-%m-%d %H:%M:%S")
