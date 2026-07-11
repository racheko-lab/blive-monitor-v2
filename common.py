#!/usr/bin/env python3
"""
直播监控 - 公共工具模块

被 check_status.py 与 check_new_posts.py 共用，避免两处重复定义
时间/JSON 读写等基础工具。
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 北京时间（UTC+8）
BEIJING_TZ = timezone(timedelta(hours=8))

# 默认 User-Agent（B站/抖音接口需要带浏览器 UA）
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def bjnow() -> datetime:
    """获取当前北京时间（naive datetime）"""
    return datetime.now(BEIJING_TZ).replace(tzinfo=None)


def load_json_file(filepath: str, default: Optional[Any] = None) -> Any:
    """安全加载 JSON 文件；文件不存在/解析失败时返回 default。"""
    if default is None:
        default = {}
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("加载 %s 失败: %s", filepath, e)
        return default


def save_json_file(filepath: str, data: Any) -> None:
    """原子保存 JSON 文件：先写同目录临时文件，再 os.replace 覆盖。

    避免运行中（CI 超时/被 kill）中断时留下半成品 JSON，导致前端读到损坏的 status.json。
    os.replace 在 POSIX/Windows 均为原子操作，且不会被工作流 `git add` 列表误提交。
    """
    tmp = f"{filepath}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, filepath)
    except IOError as e:
        logger.error("保存 %s 失败: %s", filepath, e)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


# ==================== 阶段二 2b：A3 静默 / B3 启停 / A2 路由 / A4 模板 ====================
# 以下函数被 check_status.py 与 check_new_posts.py 共用；全部为纯函数（CI 实际调用）。
# 前端 monitor.html 中有同义 JS 实现（inSilence / applyTagsFilter / applySort /
# resolveChannel / renderTemplate），此处为 Python 镜像 / 预留，保证运行时与单测一致。

def room_enabled(room: Any) -> bool:
    """房间是否启用（B3 批量启停）。

    缺失 enabled 视为 True；非 dict / enabled 非显式 False 均视为启用。
    与前端 ``room_enabled`` 语义一致：``enabled === false`` 才跳过。
    """
    if not isinstance(room, dict):
        return True
    return room.get("enabled", True) is not False


def load_silence_cfg(raw_config: str) -> Dict[str, Any]:
    """从 BLIVE_CONFIG 环境变量（JSON 字符串）解析静默配置。

    无则返回 {}（不静默）。兼容旧式（无 silence 段 / 非法 JSON）。
    """
    if not raw_config:
        return {}
    try:
        cfg = json.loads(raw_config) or {}
    except (json.JSONDecodeError, ValueError):
        return {}
    silence = cfg.get("silence") or {}
    if not isinstance(silence, dict) or not silence:
        return {}
    return {k: silence.get(k) for k in ("enabled", "start", "end")}


def in_silence(now_bj: datetime, silence: Dict[str, Any]) -> bool:
    """Python 镜像 of JS inSilence（CI 实际调用，供单测与运行时一致）。

    支持跨午夜：``start <= end`` 取 ``[start, end)``；``start > end`` 取
    ``[start, 24) ∪ [0, end)``。``silence.enabled`` 为假视为未静默。
    """
    if not silence or not silence.get("enabled"):
        return False

    def hm(s: Any) -> int:
        p = str(s or "00:00").split(":")
        h = int(p[0]) if (p and p[0].isdigit()) else 0
        m = int(p[1]) if (len(p) > 1 and p[1].isdigit()) else 0
        return h * 60 + m

    start = hm(silence.get("start"))
    end = hm(silence.get("end"))
    cur = now_bj.hour * 60 + now_bj.minute
    if start <= end:
        return start <= cur < end
    return cur >= start or cur < end  # 跨午夜


def should_skip_by_silence(now_bj: datetime, silence: Dict[str, Any]) -> bool:
    """推送前调用：silence.enabled 且当前北京时落在静默区间则暂缓（仅跳过推送）。"""
    return in_silence(now_bj, silence)


def resolve_channel(cfg: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """A2 预留：给定事件 ctx{platform?, tag?, event?} 按 routes 匹配通道。

    最具体优先（platform+tag+event > 单一维度）+ default 兜底；本波不被调用。
    无命中且无 default 时，退化为 legacy 单通道 ``cfg['push']``（兼容现有推送）。
    """
    if not isinstance(cfg, dict):
        return {}
    routes = cfg.get("routes") or []
    if not isinstance(routes, list):
        routes = []
    channels = {
        c.get("id"): c
        for c in (cfg.get("channels") or [])
        if isinstance(c, dict) and c.get("id")
    }
    platform = ctx.get("platform")
    tag = ctx.get("tag")
    event = ctx.get("event")

    def _score(m: Dict[str, Any]) -> int:
        s = 0
        if m.get("platform"):
            s += 1
        if m.get("tag"):
            s += 1
        if m.get("event"):
            s += 1
        return s

    def _match(m: Dict[str, Any]) -> bool:
        if m.get("platform") and m.get("platform") != platform:
            return False
        if m.get("tag") and m.get("tag") != tag:
            return False
        if m.get("event") and m.get("event") != event:
            return False
        return True

    default_ch: Any = None
    cands: list = []
    for r in routes:
        if not isinstance(r, dict):
            continue
        m = r.get("match") or {}
        if not m:
            default_ch = channels.get(r.get("channelId"))
            continue
        if _match(m):
            cands.append((_score(m), r))
    if cands:
        cands.sort(key=lambda x: x[0], reverse=True)
        best = cands[0][1]
        return channels.get(best.get("channelId")) or {}
    if default_ch is not None:
        return default_ch
    # 兜底：legacy 单通道（无 routes 时直用）
    return cfg.get("push") or {}


def render_template(tpl: Any, ctx: Dict[str, Any]) -> str:
    """A4 预留：替换 {name}{title}{platform}{time}{url} 等占位符。

    缺字段保留原占位符不崩（如 {name} 在 ctx 缺省时仍输出 {name}）。本波不被调用。
    """
    if tpl is None:
        return ""
    import re as _re

    def _sub(m):
        k = m.group(1)
        if ctx and k in ctx and ctx[k] not in (None, ""):
            return str(ctx[k])
        return m.group(0)

    return _re.sub(r"\{(\w+)\}", _sub, str(tpl))
