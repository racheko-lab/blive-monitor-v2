"""SQLAlchemy ORM 模型（8 张表 + rooms.kind 维度）。

字段定义见 docs/phase4_design.md §3.1 与 phase4_class.mermaid。关键设计点：
  - ``Room.kind`` ∈ {'live','post'}：同一抖音号可同时被直播监控与新作监控，
    故 UNIQUE(platform, external_id, kind)，否则丢数据（见 §7.9）。
  - ``Room.meta``（JSON）：承载平台/维度专属运行时基线（live 基线 /
    post 基线），避免新增表且字段可演进。
  - 时间列统一存北京时间字符串 ``"YYYY-MM-DD HH:MM:SS"``（与 history.json/state.json 逐字节一致）；
    ``EventHistory.occurred_ts`` 额外存 epoch 供范围查询。
"""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.utcnow()


class Room(Base):
    """监控目标表（直播 / 新作共用，用 kind 区分）。"""

    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint(
            "platform", "external_id", "kind", name="uq_room_platform_external_kind"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="live", index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    tags: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    meta: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # —— 当前直播间状态列（原 state.json/status.json 落此，GET /rooms/{id}/status 直读）——
    live_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    current_title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    online: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    area: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    cover: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_live_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    live_started_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    live_duration: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_checked_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    events: Mapped[list["EventHistory"]] = relationship(
        "EventHistory", back_populates="room", cascade="all, delete-orphan"
    )

    @property
    def key(self) -> str:
        """等价于原 JSON 键：``{platform}_{external_id}``。"""
        return f"{self.platform}_{self.external_id}"


class Post(Base):
    """新作表（可查询的作品列表，每条作品一行；基线存 Room.meta）。"""

    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("platform", "post_id", name="uq_post_platform_postid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    post_id: Mapped[str] = mapped_column(String(128), nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cover: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    published_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class EventHistory(Base):
    """统一历史事件表（替代 history.json）。"""

    __tablename__ = "events_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    raw_rid: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    account: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    platform: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    event_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    level: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prev: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    push: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    occurred_ts: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    room: Mapped[Optional["Room"]] = relationship("Room", back_populates="events")


class NotifyLog(Base):
    """通知账本：每次推送尝试（成功/失败）落一条。"""

    __tablename__ = "notify_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    event_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    target: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    sent_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)


class NotifyDedup(Base):
    """去重账本（替代 notify_dedup.json）。"""

    __tablename__ = "notify_dedup"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    last_sent_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    meta: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)


class ConfigKV(Base):
    """通用 KV 配置；BLIVE_CONFIG 存于 key='blive_config'。"""

    __tablename__ = "config_kv"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class SummaryState(Base):
    """摘要状态（替代 summary_state.json）。"""

    __tablename__ = "summary_state"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class SilenceState(Base):
    """静默状态（替代 silence_state.json）。"""

    __tablename__ = "silence_state"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
