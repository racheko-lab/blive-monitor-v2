#!/usr/bin/env python3
"""
运行时日志 + 监控日志（history.json）读写统一模块。

职责（横切收口，消除 check_status.py / check_new_posts.py 散落的日志配置）：
  - init_runtime_logging / get_logger：统一运行时日志（控制台 + 文件轮转 + 结构化上下文）。
  - HISTORY_MAX / LOG_DIR：history 上限与日志目录的「唯一来源」。
  - load_history / append_history / cap_history：history.json 的原子读写与上限裁剪。

仅依赖标准库（logging / logging.handlers / json / os）与 common.save_json_file（原子写）。
"""

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
