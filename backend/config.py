"""后端运行时配置（环境变量驱动，带合理默认值）。

所有配置项均可通过环境变量覆盖，便于 Docker / 测试注入。测试通常通过设置
``BLIVE_DB_PATH`` 指向临时库文件来隔离。
"""

import os
from typing import List

# 仓库根目录（backend/ 的上一级）
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _db_path() -> str:
    """解析 DB 路径：优先 ``BLIVE_DB_PATH``，其次 ``DATA_DIR/blive.db``，再退化到仓库 data/。"""
    explicit = os.environ.get("BLIVE_DB_PATH")
    if explicit:
        return explicit
    data_dir = os.environ.get("DATA_DIR") or os.path.join(_REPO_ROOT, "data")
    return os.path.join(data_dir, "blive.db")


# ==================== 核心配置 ====================
DB_PATH: str = _db_path()

# 内网无鉴权：``AUTH_TOKEN`` 为空时放行；非空时校验请求头 ``X-Bearer-Token``。
AUTH_TOKEN: str = os.environ.get("AUTH_TOKEN", "") or ""

# 新作品检测开关（延续原 enable_post_check 语义；默认开启）。
ENABLE_POST_CHECK: bool = _env_bool("ENABLE_POST_CHECK", True)

# 时区（scheduler / 时间展示用）。
TZ: str = os.environ.get("TZ", "Asia/Shanghai")

# 检测轮询间隔（分钟）。
LIVE_CHECK_INTERVAL_MIN: int = int(os.environ.get("LIVE_CHECK_INTERVAL_MIN", "5"))
POST_CHECK_INTERVAL_MIN: int = int(os.environ.get("POST_CHECK_INTERVAL_MIN", "10"))

# 轮询重叠保护：任务最大执行时间（秒）超过此值视为异常；misfire 宽限（秒）。
MISFIRE_GRACE_SEC: int = int(os.environ.get("MISFIRE_GRACE_SEC", "60"))

# ==================== 封面转存（transcode）配置 ====================
COVERS_DIR: str = os.environ.get("BLIVE_COVERS_DIR") or os.path.join(
    _REPO_ROOT, "assets", "covers"
)
GITHUB_OWNER: str = os.environ.get("BLIVE_GITHUB_OWNER", "racheko-lab")
GITHUB_REPO: str = os.environ.get("BLIVE_GITHUB_REPO", "blive-monitor")
GITHUB_BRANCH: str = os.environ.get("BLIVE_GITHUB_BRANCH", "master")

# API 前缀（设计 §3.3：/api/v1）。
API_PREFIX: str = os.environ.get("BLIVE_API_PREFIX", "/api/v1")

# 健康检查豁免鉴权的路径（与读接口一起豁免）。
PUBLIC_PATHS: List[str] = ["/healthz"]

# 去重冷却（秒）：与主 notify_dedup.LIVE_COOLDOWN_SECONDS 保持一致。
LIVE_DEDUP_COOLDOWN_SEC: int = 7200
