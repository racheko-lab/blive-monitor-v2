#!/usr/bin/env python3
"""
运行时日志 + 监控日志（history.json）读写统一模块。

职责（横切收口，消除 check_status.py / check_new_posts.py 散落的日志配置）：
  - init_runtime_logging / get_logger：统一运行时日志（控制台 + 文件轮转 + 结构化上下文）。
  - HISTORY_MAX / LOG_DIR：history 上限与日志目录的「唯一来源」。
  - load_history / append_history / cap_history：history.json 的原子读写与上限裁剪。

仅依赖标准库（logging / logging.handlers / json / os）与 common.save_json_file（原子写）。
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import logging
import logging.handlers
import os

import common

# ==================== 全局常量（唯一来源） ====================

# 历史日志保留条数（check_status.py 与 merge_state.py 均引用此处，禁止各自再定义）
HISTORY_MAX: int = 500

# 运行时日志目录（被 .gitignore 忽略，仅作本地/CI 排障留存）
LOG_DIR: str = "logs"

# 运行时日志文件名
_RUNTIME_LOG_NAME: str = "runtime.log"
# 单文件上限 5MB，保留 5 个备份（轮转）
_ROTATE_MAX_BYTES: int = 5 * 1024 * 1024
_ROTATE_BACKUP_COUNT: int = 5


# ==================== 日志分级 / 统一模型（日志模块功能性重写） ====================

# 事件 type 枚举（单一来源；前端 JS 必须使用完全相同的字符串值）
EVENT_TYPES: frozenset = frozenset({
    "live_on",      # 开播
    "live_off",     # 下播 / 回放结束
    "new_post",     # 抖音新作品
    "error",        # 检测异常 / 抓取失败
    "cookie_warn",  # 风控拦截 / 需 Cookie / 解析失败
    "system",       # 系统事件（账号增删 / 基线初始化 / 配置变更）
})

# 严重级（二级，可选字段；缺省由 type 推导）
LEVELS: frozenset = frozenset({"info", "warn", "error"})

# 错误类事件节流窗口（分钟）：同 rid+type 在该窗口内不重复写入 history（防刷屏）
ERROR_THROTTLE_MINUTES: int = 30

# 受节流约束的 type（仅 error/cookie_warn；new_post/system/live_* 始终写入）
_THROTTLE_TYPES: frozenset = frozenset({"error", "cookie_warn"})

# status（旧字段）→ type 推导（未知状态归为 system）
STATUS_TO_TYPE: Dict[str, str] = {
    "live": "live_on",
    "offline": "live_off",
    "replay": "live_off",
    "error": "error",
}

# type → level 推导（缺省 info）
TYPE_TO_LEVEL: Dict[str, str] = {
    "live_on": "info",
    "live_off": "info",
    "new_post": "info",
    "system": "info",
    "cookie_warn": "warn",
    "error": "error",
}


def type_from_status(status: Optional[str]) -> str:
    """把旧 ``status`` 字段推导为统一 ``type`` 枚举值；未知状态归为 ``system``。"""
    if status is None:
        return "system"
    return STATUS_TO_TYPE.get(status, "system")


def level_from_type(t: Optional[str]) -> str:
    """由 ``type`` 推导严重级；未知 ``type`` 缺省 ``info``。"""
    if t is None:
        return "info"
    return TYPE_TO_LEVEL.get(t, "info")


class _ContextFilter(logging.Filter):
    """为每条记录补充 ``account`` 字段（缺省空串）。

    日志格式串引用了 %(account)s；若记录缺失该字段，Formatter 会抛 KeyError。
    此过滤器保证「所有」经本模块 handler 的记录都带有 account（缺省 ""），
    从而使既有的 ``logger.info(...)`` 调用无需任何改动即可正常工作。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "account"):
            record.account = ""
        return True


def init_runtime_logging(level: int = logging.INFO, log_dir: str = LOG_DIR) -> None:
    """初始化运行时日志：控制台 + RotatingFileHandler 落盘 ``logs/runtime.log``。

    格式：``%(asctime)s [%(levelname)s] %(name)s %(account)s %(message)s``
    其中 ``account`` 缺省为空串（由 _ContextFilter 保障），不影响既有输出解析。

    幂等性：若 root logger 已存在 handler（例如已在同进程初始化、或运行于 pytest
    等已配置日志的宿主环境），则不再重复添加，避免覆盖/干扰外部日志配置。

    Args:
        level: 日志级别，默认 ``logging.INFO``。
        log_dir: 日志目录，默认 ``LOG_DIR``（"logs"）。
    """
    os.makedirs(log_dir, exist_ok=True)
    root = logging.getLogger()
    # 已有 handler（pytest / 重复调用）时不重复添加，保护外部配置
    if root.handlers:
        return

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s %(account)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    ctx_filter = _ContextFilter()

    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, _RUNTIME_LOG_NAME),
        maxBytes=_ROTATE_MAX_BYTES,
        backupCount=_ROTATE_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(ctx_filter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.addFilter(ctx_filter)

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.setLevel(level)


class _AccountAdapter(logging.LoggerAdapter):
    """携带 account 上下文的 LoggerAdapter：在记录中注入 account 字段。"""

    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        extra = kwargs.setdefault("extra", {})
        extra["account"] = self.extra.get("account", "")
        return msg, kwargs


def get_logger(name: str, account: Optional[str] = None) -> logging.LoggerAdapter:
    """返回带 account 上下文的 logger（LoggerAdapter）。

    account 缺省为空串；未提供时日志中 %(account)s 为空，与既有输出兼容。
    适合为每个账号/房间单独打日志，便于在 runtime.log 中按 account 检索。

    Args:
        name: logger 名称（通常传 ``__name__``）。
        account: 可选上下文（如房间 id / 抖音号），缺省空串。

    Returns:
        带上下文的 ``LoggerAdapter``。
    """
    base = logging.getLogger(name)
    return _AccountAdapter(base, {"account": account or ""})


# ==================== history.json 读写 / 上限 ====================

def load_history(path: str) -> List[Dict[str, Any]]:
    """安全加载 history.json，返回 list[dict]（缺失/损坏返回 []）。

    Args:
        path: history.json 路径。

    Returns:
        历史条目列表；非 list 时返回 []。
    """
    data = common.load_json_file(path, [])
    if not isinstance(data, list):
        return []
    return data


def cap_history(entries: List[Dict[str, Any]], max_n: int) -> List[Dict[str, Any]]:
    """保留最近 ``max_n`` 条（尾部），返回新列表（不改写原列表）。

    Args:
        entries: 历史条目列表。
        max_n: 保留条数上限；非正数表示不裁剪。

    Returns:
        裁剪后的列表。
    """
    if not isinstance(entries, list):
        return []
    if not isinstance(max_n, int) or max_n <= 0:
        return entries
    if len(entries) > max_n:
        return entries[-max_n:]
    return entries


def append_history(path: str, new_entries: List[Dict[str, Any]], max_n: int) -> int:
    """把新条目追加到 history.json（原子写），保留最近 ``max_n`` 条。

    Args:
        path: history.json 路径。
        new_entries: 本轮新增的条目列表。
        max_n: 保留条数上限。

    Returns:
        写回后的最终条数。
    """
    if not isinstance(new_entries, list):
        new_entries = list(new_entries) if new_entries is not None else []
    history = load_history(path)
    history = history + new_entries
    history = cap_history(history, max_n)
    common.save_json_file(path, history)
    return len(history)


# ==================== 节流 / 统计（日志模块功能性重写） ====================

def _parse_time(ts: Any) -> Optional[datetime]:
    """把 time 字段解析为 naive datetime（北京时间字符串或 datetime）；失败返回 None。"""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None) if ts.tzinfo else ts
    if isinstance(ts, str):
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                # 兼容 "YYYY-MM-DDTHH:MM:SS" 或带 Z 的格式
                return datetime.fromisoformat(ts.replace("Z", "").replace("T", " "))
            except Exception:
                return None
    return None


def should_suppress(
    rid: Optional[str],
    etype: Optional[str],
    now: Any,
    history_path: Optional[str] = None,
    in_memory: Optional[List[Dict[str, Any]]] = None,
    window_minutes: int = ERROR_THROTTLE_MINUTES,
) -> bool:
    """判断同 ``rid+type`` 的事件在节流窗口内是否已被写过（跨进程/跨脚本基于磁盘 history）。

    合并 ``in_memory``（本运行 pending）+ 磁盘 ``history.json`` 末尾 N 条联合判断：
    任一处存在同 ``rid+type`` 且 ``time`` 距 ``now`` < 窗口，则视为应抑制（返回 True）。

    Args:
        rid: 账号主键（与 history 的 ``rid`` 同源）；为空视为不抑制。
        etype: 事件 type（见 ``EVENT_TYPES``）；为空视为不抑制。
        now: 当前时间（datetime 或 "YYYY-MM-DD HH:MM:SS" 字符串）。
        history_path: 磁盘 history.json 路径（None 则仅看内存 pending）。
        in_memory: 本运行内已打算写入的 pending 列表（用于同轮多账号失败互相抑制）。
        window_minutes: 节流窗口（分钟），默认 ``ERROR_THROTTLE_MINUTES``。

    Returns:
        是否应抑制（True=窗口内已写过，跳过）。
    """
    if not rid or not etype:
        return False
    now_dt = _parse_time(now)
    if now_dt is None:
        return False
    cutoff = now_dt - timedelta(minutes=window_minutes)

    # 1) 本运行内存 pending（同轮多次失败互相抑制）
    if in_memory:
        for e in in_memory:
            if not isinstance(e, dict):
                continue
            if e.get("rid") == rid and e.get("type") == etype:
                t = _parse_time(e.get("time"))
                if t is not None and t >= cutoff:
                    return True

    # 2) 磁盘末尾 N 条（跨进程/跨脚本，history.json 是唯一真相源）
    if history_path:
        hist = load_history(history_path)
        tail = hist[-50:]
        for e in tail:
            if not isinstance(e, dict):
                continue
            if e.get("rid") == rid and e.get("type") == etype:
                t = _parse_time(e.get("time"))
                if t is not None and t >= cutoff:
                    return True
    return False


def dedupe_by_throttle(
    entries: List[Dict[str, Any]],
    now: Any,
    history_path: Optional[str] = None,
    in_memory: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """对 ``error`` / ``cookie_warn`` 类条目做节流去重；其余（info/new_post/system）始终保留。

    维护 running ``in_memory``（与传入同一列表对象）使同轮内也抑制。仅剔除窗口内重复的
    错误类条目，返回过滤后的新列表（不改动入参）。

    Args:
        entries: 本轮构建的 history 条目列表。
        now: 当前时间。
        history_path: 磁盘 history.json 路径（用于跨进程抑制）。
        in_memory: 运行内 pending 列表（可变，本函数会向其中追加被保留的错误条目）。

    Returns:
        过滤后的条目列表。
    """
    if not isinstance(entries, list):
        return []
    out: List[Dict[str, Any]] = []
    pending = list(in_memory) if in_memory else []
    for e in entries:
        if not isinstance(e, dict):
            continue
        etype = e.get("type")
        if etype in _THROTTLE_TYPES:
            rid = e.get("rid")
            if should_suppress(rid, etype, now, history_path=history_path, in_memory=pending):
                continue
            pending.append(e)
        out.append(e)
    return out


def compute_stats(
    history: List[Dict[str, Any]],
    days: int = 7,
    now: Any = None,
) -> Dict[str, Any]:
    """按 type + 北京时间日期聚合到天，返回近 ``days`` 天每日计数。

    口径（与前端 ``computeStatsJS`` 一致）：
      - ``new_post``：每日新作品数；
      - ``live_on``：每日开播次数；
      - ``error`` / ``cookie_warn``：每日异常/风控计数（P1-3）。

    Args:
        history: history.json 条目列表。
        days: 统计天数（默认 7）。
        now: 基准时间（默认 ``common.bjnow()``）。

    Returns:
        形如 ``{days:[标签...], new_post:[...], live_on:[...], error:[...],
        cookie_warn:[...], totals:{...}}`` 的字典。
    """
    base = _parse_time(now) if now is not None else common.bjnow()
    if base is None:
        base = common.bjnow()
    buckets = {
        "new_post": [0] * days,
        "live_on": [0] * days,
        "error": [0] * days,
        "cookie_warn": [0] * days,
    }
    labels: List[str] = []
    idx: Dict[str, int] = {}
    for i in range(days - 1, -1, -1):
        d = base - timedelta(days=i)
        lab = d.strftime("%m-%d")
        labels.append(lab)
        idx[lab] = days - 1 - i
    for e in history:
        if not isinstance(e, dict):
            continue
        t = e.get("type")
        if t not in buckets:
            continue
        dt = _parse_time(e.get("time"))
        if dt is None:
            continue
        lab = dt.strftime("%m-%d")
        if lab in idx:
            buckets[t][idx[lab]] += 1
    totals = {k: sum(v) for k, v in buckets.items()}
    return {
        "days": labels,
        "new_post": buckets["new_post"],
        "live_on": buckets["live_on"],
        "error": buckets["error"],
        "cookie_warn": buckets["cookie_warn"],
        "totals": totals,
    }
