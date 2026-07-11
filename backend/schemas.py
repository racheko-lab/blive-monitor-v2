"""Pydantic 请求/响应模型（API 契约，见设计 §3.3）。

所有时间字段统一 ``"YYYY-MM-DD HH:MM:SS"``（北京时间）。``RoomOut`` 含 rooms 全部列
（含 meta / live_status 等）；``EventOut`` 含 events_history 全部列。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ==================== Room ====================
class RoomBase(BaseModel):
    platform: str = Field(..., examples=["bilibili"])
    external_id: str = Field(..., examples=["22230707"])
    kind: str = Field("live", examples=["live", "post"])
    name: str = ""
    title: str = ""
    tags: Optional[Any] = None
    enabled: bool = True
    meta: Optional[Dict[str, Any]] = None


class RoomCreate(RoomBase):
    """新增监控目标。"""


class RoomUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    tags: Optional[Any] = None
    enabled: Optional[bool] = None
    meta: Optional[Dict[str, Any]] = None


class RoomStatusUpdate(BaseModel):
    live_status: Optional[str] = None
    title: Optional[str] = None
    cover: Optional[str] = None
    online: Optional[int] = None
    area: Optional[str] = None


class RoomStatusOut(BaseModel):
    live_status: Optional[str] = None
    current_title: Optional[str] = None
    online: int = 0
    area: Optional[str] = None
    cover: Optional[str] = None
    last_live_at: Optional[str] = None
    live_started_at: Optional[str] = None
    live_duration: Optional[str] = None
    last_checked_at: Optional[str] = None


class RoomOut(RoomBase):
    id: int
    live_status: Optional[str] = None
    current_title: Optional[str] = None
    online: int = 0
    area: Optional[str] = None
    cover: Optional[str] = None
    last_live_at: Optional[str] = None
    live_started_at: Optional[str] = None
    live_duration: Optional[str] = None
    last_checked_at: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ==================== Post ====================
class PostCreate(BaseModel):
    platform: str
    post_id: str
    author: Optional[str] = None
    url: Optional[str] = None
    cover: Optional[str] = None
    published_at: Optional[str] = None


class PostOut(BaseModel):
    id: int
    platform: str
    post_id: str
    author: Optional[str] = None
    url: Optional[str] = None
    cover: Optional[str] = None
    published_at: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ==================== Event ====================
class EventOut(BaseModel):
    id: int
    room_id: Optional[int] = None
    raw_rid: Optional[str] = None
    account: Optional[str] = None
    platform: Optional[str] = None
    event_type: Optional[str] = None
    name: Optional[str] = None
    title: Optional[str] = None
    detail: Optional[str] = None
    level: Optional[str] = None
    changed: bool = False
    prev: Optional[str] = None
    push: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    occurred_at: Optional[str] = None
    occurred_ts: Optional[int] = None

    model_config = {"from_attributes": True}


# ==================== Notify ====================
class NotifyLogIn(BaseModel):
    channel_id: Optional[str] = None
    event_type: Optional[str] = None
    target: Optional[str] = None
    content_hash: Optional[str] = None
    status: str = "ok"


class NotifyLogOut(BaseModel):
    id: int
    channel_id: Optional[str] = None
    event_type: Optional[str] = None
    target: Optional[str] = None
    content_hash: Optional[str] = None
    sent_at: Optional[str] = None
    status: Optional[str] = None

    model_config = {"from_attributes": True}


class DedupUpsert(BaseModel):
    key: str
    meta: Optional[Dict[str, Any]] = None


class DedupQueryOut(BaseModel):
    exists: bool
    last_sent_at: float = 0.0


# ==================== Config / Summary / Silence ====================
class SummaryStateOut(BaseModel):
    enabled: bool = False
    freq: str = "daily"
    sendTime: str = "00:00"
    lastSent: int = 0
    lastFailedAt: Optional[int] = None
    lastFailedSince: Optional[int] = None


class SilenceStateOut(BaseModel):
    enabled: bool = False
    start: str = "23:00"
    end: str = "08:00"


# ==================== 通用 ====================
class HealthOut(BaseModel):
    status: str = "ok"
    db: bool = True


class JobTriggerOut(BaseModel):
    job_id: str
    type: str
    status: str = "accepted"


class PagedRooms(BaseModel):
    total: int
    items: List[RoomOut]


class PagedEvents(BaseModel):
    total: int
    items: List[EventOut]


class PagedPosts(BaseModel):
    total: int
    items: List[PostOut]
