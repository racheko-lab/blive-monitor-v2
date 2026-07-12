"""适配器抽象基类 + 归一化模型（阶段三 T01）。

设计要点（docs/phase3_design.md §3）：
- RoomModel / PostModel：与 backend/models.py 的 Room / Post ORM 逐字段对齐，
  作为「适配器 → 编排层」之间的归一化契约。适配器只产出模型，绝不写 DB/JSON。
- PlatformAdapter：所有平台适配器的抽象基类，定义 fetch_room_status /
  fetch_new_posts 能力与能力标志（supports_live / supports_posts）。

硬约束（§8）：适配器内部绝不直写 JSON/DB；只 fetch + 归一化 return 模型，
所有落库/推送一律回到编排层（check_status.run_live_check /
check_new_posts.run_post_check → persist 门面 → push_utils）。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class RoomModel:
    """直播房间归一化模型（对齐 Room(kind='live')）。

    live_status 为归一化 BOOL（True=直播中）；编排层在写入 Room.live_status 列前
    映射为 "live"/"offline"（或异常 "error"）。extra 承载平台专属基线（如 douyin 的
    sec_uid、bilibili 的 raw 状态串），由编排层并入 Room.meta（阶段四「基线存 meta」约定）。
    """

    platform: str = ""
    room_id: str = ""
    name: str = ""
    title: str = ""
    live_status: bool = False
    url: str = ""
    cover: str = ""
    tags: List[str] = field(default_factory=list)
    online: int = 0
    area: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PostModel:
    """新作归一化模型（对齐 Post）。

    published_at 一律北京时间字符串 "YYYY-MM-DD HH:MM:SS"。extra 承载平台专属信息
    （类型/置信度/解析到的 sec_uid/去重键/推测模式的前后计数等）。
    """

    platform: str = ""
    post_id: str = ""
    author: str = ""
    url: str = ""
    cover: str = ""
    published_at: str = ""
    title: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


class AdapterError(Exception):
    """适配器检测异常基类。"""


class AdapterSkip(AdapterError):
    """跳过该账号（不推送）。reason ∈ {"no_sec_uid", "poisoned", ...}。

    编排层据 reason 决定记 system 事件（no_sec_uid）或直接静默跳过（poisoned）。
    """

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(detail or reason)


class AdapterGated(AdapterError):
    """接口被风控/未登录，无真实数据（编排层等价原 cookie_warn 事件）。"""

    def __init__(self, detail: str = ""):
        self.detail = detail
        super().__init__(detail or "gated")


class PlatformAdapter(ABC):
    """平台适配器抽象基类。

    子类必须定义类常量 ``platform``；可按需覆写 ``supports_live`` / ``supports_posts`` /
    ``poll_interval`` / ``rate_limit`` / ``needs_context``。``fetch_room_status`` 与
    ``fetch_new_posts`` 为核心检测入口，子类实现之；``fetch_room_status_batch`` 为可选
    批量优化（bilibili 实现），未实现时编排层逐房间回退。
    """

    #: 平台代码（如 "kuaishou" / "bilibili"），子类必须覆盖
    platform: str = ""

    #: 默认轮询间隔（秒）；可被 config.platforms 覆盖
    poll_interval: int = 300

    #: 限流配置 {max_requests, window_sec, backoff_sec}
    rate_limit: Dict[str, Any] = field(default_factory=dict)

    #: 是否支持直播检测
    supports_live: bool = True

    #: 是否支持新作检测
    supports_posts: bool = True

    #: 检测是否需要 Playwright 无头浏览器上下文（douyin/xhs/channels/taobao_live=True）
    needs_context: bool = False

    def __init__(
        self,
        credentials: Dict[str, Any] = None,
        poll_interval: Optional[int] = None,
        rate_limit: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.credentials: Dict[str, Any] = dict(credentials or {})
        if poll_interval is not None:
            self.poll_interval = int(poll_interval)
        if rate_limit is not None:
            self.rate_limit = dict(rate_limit)

    @abstractmethod
    def fetch_room_status(self, room_id: str) -> RoomModel:
        """取单房间直播状态。

        不支持直播的平台（如 xhs）抛 ``NotImplementedError``，由编排层按
        ``supports_live`` 提前跳过，不会触发。检测失败应优雅降级为
        ``RoomModel(live_status=False)``（不抛未捕获异常，避免中断整轮检测）。

        Returns:
            归一化 ``RoomModel``（``live_status`` 为 BOOL）。
        """
        raise NotImplementedError

    @abstractmethod
    def fetch_new_posts(
        self,
        author_or_room: str,
        since: Optional[datetime] = None,
        baseline: Optional[Dict[str, Any]] = None,
        context: Any = None,
    ) -> List[PostModel]:
        """取作者/房间自 ``since`` 以来的新作。

        不支持新作的平台（如 taobao_live）抛 ``NotImplementedError``，由编排层
        按 ``supports_posts`` 提前跳过。

        Args:
            author_or_room: 作者标识 / 房间号（平台专属含义）。
            since: 时间下界（可选）。
            baseline: 平台专属先验基线（如 douyin 的 sec_uid），可原地更新回写。
            context: 可选 Playwright BrowserContext（需无头浏览器的平台使用）。

        Returns:
            归一化 ``PostModel`` 列表（已按平台逻辑判定为「新于基线」的作品）。
        """
        raise NotImplementedError

    def fetch_room_status_batch(self, room_ids: List[str]) -> Dict[str, RoomModel]:
        """批量取房间直播状态（可选优化，默认逐房间回退）。

        bilibili 实现以保留官方批量接口效率；其余平台不实现，编排层逐房间调用
        ``fetch_room_status``。
        """
        return {str(rid): self.fetch_room_status(str(rid)) for rid in room_ids}

    def apply_credentials(self, context: Any) -> None:
        """可选的凭证注入钩子（如注入登录 Cookie 到 Playwright 上下文）。默认无操作。"""
        return None
