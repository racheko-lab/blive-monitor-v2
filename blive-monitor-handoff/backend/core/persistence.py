"""Persistence：rooms / posts / events 的 DB 落库实现。

职责（设计 §3.2）：
  - ``set_room_status``：写 Room 状态列 + 合并 meta 基线（live/post 基线）。
  - ``append_event``：写 events_history（节流逻辑在 HistoryStore，本类仅落盘）。
  - ``record_notify`` / ``upsert_post_baseline`` / ``get_room`` / ``list_rooms`` 等。

约定（§7.8）：所有写操作持 ``db.WRITER_LOCK`` 串行化。每个公开方法内部使用独立的短生命周期
Session（避免在 scheduler 后台线程与 API 线程间共享 Session）。

注意：events_history 的实际写入由 ``HistoryStore`` 提供（含 30min 节流）；本类的
``append_event`` 仅做裸落盘，供 HistoryStore 在节流放行后调用。
"""

from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import db
from ..models import EventHistory, Post, Room


class Persistence:
    """rooms / posts / events_history 的数据库读写封装。"""

    # ---------- session 作用域 ----------
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

    # ==================== Room 读写 ====================
    def list_rooms(
        self,
        kind: Optional[str] = None,
        platform: Optional[str] = None,
        enabled: Optional[bool] = None,
        q: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Room]:
        with self._session_scope() as s:
            qry = s.query(Room)
            if kind is not None:
                qry = qry.filter(Room.kind == kind)
            if platform is not None:
                qry = qry.filter(Room.platform == platform)
            if enabled is not None:
                qry = qry.filter(Room.enabled == enabled)
            if q:
                like = f"%{q}%"
                qry = qry.filter(or_(Room.name.like(like), Room.external_id.like(like)))
            qry = qry.order_by(Room.id.asc()).limit(limit).offset(offset)
            return qry.all()

    def count_rooms(
        self,
        kind: Optional[str] = None,
        platform: Optional[str] = None,
        enabled: Optional[bool] = None,
        q: Optional[str] = None,
    ) -> int:
        with self._session_scope() as s:
            qry = s.query(func.count(Room.id))
            if kind is not None:
                qry = qry.filter(Room.kind == kind)
            if platform is not None:
                qry = qry.filter(Room.platform == platform)
            if enabled is not None:
                qry = qry.filter(Room.enabled == enabled)
            if q:
                like = f"%{q}%"
                qry = qry.filter(or_(Room.name.like(like), Room.external_id.like(like)))
            return int(qry.scalar() or 0)

    def get_room(self, room_id: int) -> Optional[Room]:
        with self._session_scope() as s:
            return s.get(Room, room_id)

    def get_room_by_key(
        self, platform: str, external_id: str, kind: str
    ) -> Optional[Room]:
        with self._session_scope() as s:
            return (
                s.query(Room)
                .filter(
                    Room.platform == platform,
                    Room.external_id == external_id,
                    Room.kind == kind,
                )
                .first()
            )

    def upsert_room(self, data: Dict[str, Any]) -> Room:
        """按 (platform, external_id, kind) 幂等 upsert 一个 Room。"""
        platform = data["platform"]
        external_id = str(data["external_id"])
        kind = data.get("kind", "live")
        with db.WRITER_LOCK:
            with self._session_scope() as s:
                room = (
                    s.query(Room)
                    .filter(
                        Room.platform == platform,
                        Room.external_id == external_id,
                        Room.kind == kind,
                    )
                    .first()
                )
                if room is None:
                    room = Room(
                        platform=platform,
                        external_id=external_id,
                        kind=kind,
                    )
                    s.add(room)
                room.platform = platform
                room.external_id = external_id
                room.kind = kind
                if "name" in data:
                    room.name = data["name"]
                if "title" in data:
                    room.title = data["title"]
                if "tags" in data:
                    room.tags = data["tags"]
                if "enabled" in data:
                    room.enabled = bool(data["enabled"])
                if "meta" in data and data["meta"] is not None:
                    room.meta = data["meta"]
                s.flush()
                # 返回 detached 副本（避免跨 session 使用）
                s.refresh(room)
                return Room(
                    id=room.id,
                    kind=room.kind,
                    platform=room.platform,
                    external_id=room.external_id,
                    name=room.name,
                    title=room.title,
                    tags=room.tags,
                    enabled=room.enabled,
                    meta=room.meta,
                    live_status=room.live_status,
                    current_title=room.current_title,
                    online=room.online,
                    area=room.area,
                    cover=room.cover,
                    last_live_at=room.last_live_at,
                    live_started_at=room.live_started_at,
                    live_duration=room.live_duration,
                    last_checked_at=room.last_checked_at,
                    created_at=room.created_at,
                    updated_at=room.updated_at,
                )

    def update_room(self, room_id: int, data: Dict[str, Any]) -> Optional[Room]:
        with db.WRITER_LOCK:
            with self._session_scope() as s:
                room = s.get(Room, room_id)
                if room is None:
                    return None
                for fld in ("name", "title", "tags", "enabled", "meta"):
                    if fld in data and data[fld] is not None:
                        if fld == "enabled":
                            setattr(room, fld, bool(data[fld]))
                        else:
                            setattr(room, fld, data[fld])
                s.flush()
                # 直接返回当前会话中已修改的对象（expire_on_commit=False 保证关闭后仍可读）；
                # 不可在写事务内再起一个嵌套 session 去读未提交的 schrijf（SQLite 看不到）。
                return room

    def delete_room(self, room_id: int) -> bool:
        with db.WRITER_LOCK:
            with self._session_scope() as s:
                room = s.get(Room, room_id)
                if room is None:
                    return False
                s.delete(room)
                return True

    # ==================== 状态列 / 基线 ====================
    def get_room_status(self, platform: str, external_id: str, kind: str) -> Optional[str]:
        room = self.get_room_by_key(platform, external_id, kind)
        return room.live_status if room else None

    def get_tracking(self, platform: str, external_id: str, kind: str) -> Dict[str, Any]:
        room = self.get_room_by_key(platform, external_id, kind)
        return dict(room.meta or {}) if room else {}

    def set_room_status(
        self,
        *,
        platform: str,
        external_id: str,
        kind: str,
        name: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        meta_update: Optional[Dict[str, Any]] = None,
        now_str: Optional[str] = None,
        status_item: Optional[Dict[str, Any]] = None,
    ) -> Room:
        """写 Room 状态列 + 合并 meta 基线（幂等 upsert）。

        Args:
            status_item: 等价 status.json 单间字段（platform/id/name/status/title/online/area/
                time/sec_uid/last_live/live_duration），用于回填状态列。
            meta_update: 需合并进 Room.meta 的基线字段（如 live 基线的 last_live/live_start/
                live_duration/last_duration/sec_uid，或 post 基线字段）。
        """
        result = result or {}
        status_item = status_item or {}
        with db.WRITER_LOCK:
            with self._session_scope() as s:
                room = (
                    s.query(Room)
                    .filter(
                        Room.platform == platform,
                        Room.external_id == external_id,
                        Room.kind == kind,
                    )
                    .first()
                )
                if room is None:
                    room = Room(
                        platform=platform,
                        external_id=external_id,
                        kind=kind,
                    )
                    s.add(room)

                # 名称优先 status_item.name（检测期可能从昵称回填）。
                if name:
                    room.name = name
                elif status_item.get("name"):
                    room.name = status_item["name"]

                room.live_status = status_item.get("status") or result.get("status")
                room.current_title = status_item.get("title") or result.get("title")
                room.online = int(status_item.get("online", result.get("online", 0)) or 0)
                room.area = status_item.get("area") or result.get("area")
                room.last_checked_at = status_item.get("time") or now_str
                if status_item.get("last_live"):
                    room.last_live_at = status_item["last_live"]
                if status_item.get("live_duration"):
                    room.live_duration = status_item["live_duration"]
                # live_start 来自 meta（基线），由 meta_update 合并。
                if "live_start" in (meta_update or {}):
                    room.live_started_at = meta_update.get("live_start") or None
                if "cover" in (meta_update or {}):
                    room.cover = meta_update.get("cover")
                elif status_item.get("sec_uid"):
                    # douyin 封面兜底：保留 meta 中的 latest_cover（见 transcode）
                    pass

                # 合并 meta 基线（保留既有字段）。
                base = dict(room.meta or {})
                if meta_update:
                    base.update(meta_update)
                room.meta = base

                s.flush()
                # 返回当前会话中的对象（写事务内不可再起嵌套 session 读取未提交行）。
                return room

    # ==================== events_history ====================
    def append_event(self, entry: Dict[str, Any]) -> EventHistory:
        """裸落盘一条事件（节流由 HistoryStore 负责，本方法不节流）。"""
        with db.WRITER_LOCK:
            with self._session_scope() as s:
                ev = EventHistory(
                    room_id=entry.get("room_id"),
                    raw_rid=entry.get("raw_rid") or entry.get("rid"),
                    account=entry.get("account") or entry.get("rid"),
                    platform=entry.get("platform"),
                    event_type=entry.get("type") or entry.get("event_type"),
                    name=entry.get("name"),
                    title=entry.get("title"),
                    detail=entry.get("detail"),
                    level=entry.get("level"),
                    changed=bool(entry.get("changed", False)),
                    prev=entry.get("prev"),
                    push=entry.get("push"),
                    payload=entry.get("payload"),
                    occurred_at=entry.get("time") or entry.get("occurred_at"),
                    occurred_ts=entry.get("occurred_ts"),
                )
                s.add(ev)
                s.flush()
                # 构造返回值（detached）
                return EventHistory(
                    id=ev.id,
                    room_id=ev.room_id,
                    raw_rid=ev.raw_rid,
                    account=ev.account,
                    platform=ev.platform,
                    event_type=ev.event_type,
                    name=ev.name,
                    title=ev.title,
                    detail=ev.detail,
                    level=ev.level,
                    changed=ev.changed,
                    prev=ev.prev,
                    push=ev.push,
                    payload=ev.payload,
                    occurred_at=ev.occurred_at,
                    occurred_ts=ev.occurred_ts,
                )

    def list_events(
        self,
        room_id: Optional[int] = None,
        platform: Optional[str] = None,
        event_type: Optional[str] = None,
        frm: Optional[str] = None,
        to: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[EventHistory]:
        with self._session_scope() as s:
            qry = s.query(EventHistory)
            if room_id is not None:
                qry = qry.filter(EventHistory.room_id == room_id)
            if platform is not None:
                qry = qry.filter(EventHistory.platform == platform)
            if event_type is not None:
                qry = qry.filter(EventHistory.event_type == event_type)
            if frm:
                qry = qry.filter(EventHistory.occurred_at >= frm)
            if to:
                qry = qry.filter(EventHistory.occurred_at <= to)
            qry = qry.order_by(EventHistory.id.desc()).limit(limit).offset(offset)
            return qry.all()

    def count_events(
        self,
        room_id: Optional[int] = None,
        platform: Optional[str] = None,
        event_type: Optional[str] = None,
        frm: Optional[str] = None,
        to: Optional[str] = None,
    ) -> int:
        with self._session_scope() as s:
            qry = s.query(func.count(EventHistory.id))
            if room_id is not None:
                qry = qry.filter(EventHistory.room_id == room_id)
            if platform is not None:
                qry = qry.filter(EventHistory.platform == platform)
            if event_type is not None:
                qry = qry.filter(EventHistory.event_type == event_type)
            if frm:
                qry = qry.filter(EventHistory.occurred_at >= frm)
            if to:
                qry = qry.filter(EventHistory.occurred_at <= to)
            return int(qry.scalar() or 0)

    # ==================== posts ====================
    def upsert_post(self, data: Dict[str, Any]) -> Post:
        platform = data["platform"]
        post_id = str(data["post_id"])
        with db.WRITER_LOCK:
            with self._session_scope() as s:
                post = (
                    s.query(Post)
                    .filter(Post.platform == platform, Post.post_id == post_id)
                    .first()
                )
                if post is None:
                    post = Post(platform=platform, post_id=post_id)
                    s.add(post)
                for fld in ("author", "url", "cover", "published_at"):
                    if fld in data and data[fld] is not None:
                        setattr(post, fld, data[fld])
                s.flush()
                # 返回当前会话中的对象（避免嵌套 session 读取未提交行）。
                return post

    def get_post(self, post_id: int) -> Optional[Post]:
        with self._session_scope() as s:
            return s.get(Post, post_id)

    def list_posts(
        self,
        platform: Optional[str] = None,
        author: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Post]:
        with self._session_scope() as s:
            qry = s.query(Post)
            if platform is not None:
                qry = qry.filter(Post.platform == platform)
            if author is not None:
                qry = qry.filter(Post.author == author)
            if since:
                qry = qry.filter(Post.published_at >= since)
            qry = qry.order_by(Post.id.desc()).limit(limit).offset(offset)
            return qry.all()

    def count_posts(
        self,
        platform: Optional[str] = None,
        author: Optional[str] = None,
        since: Optional[str] = None,
    ) -> int:
        with self._session_scope() as s:
            qry = s.query(func.count(Post.id))
            if platform is not None:
                qry = qry.filter(Post.platform == platform)
            if author is not None:
                qry = qry.filter(Post.author == author)
            if since:
                qry = qry.filter(Post.published_at >= since)
            return int(qry.scalar() or 0)
