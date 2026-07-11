"""多平台适配器包（阶段三 T01）。

导出归一化模型、抽象基类与适配器注册表。适配器全部位于后端侧，复用阶段四
persist / push_utils 做落库与推送（适配器内部绝不写 DB/JSON）。
"""

from backend.adapters.base import (
    AdapterError,
    AdapterGated,
    AdapterSkip,
    PlatformAdapter,
    PostModel,
    RoomModel,
)
from backend.adapters.registry import AdapterRegistry

__all__ = [
    "PlatformAdapter",
    "RoomModel",
    "PostModel",
    "AdapterError",
    "AdapterSkip",
    "AdapterGated",
    "AdapterRegistry",
]
