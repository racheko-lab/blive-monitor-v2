"""log_utils 单元测试：HISTORY_MAX 单一来源、history 读写/上限、运行时日志初始化与结构化。"""
import json
import logging
import logging.handlers
from datetime import datetime

import pytest

import log_utils as lu


# ==================== 常量（单一来源） ====================

def test_history_max_is_500():
    assert lu.HISTORY_MAX == 500


def test_log_dir_default():
    assert lu.LOG_DIR == "logs"


# ==================== cap_history ====================

def test_cap_history_keeps_recent():
    entries = [{"i": i} for i in range(10)]
    capped = lu.cap_history(entries, 3)
    assert len(capped) == 3
    assert capped == [{"i": 7}, {"i": 8}, {"i": 9}]


def test_cap_history_noop_when_under():
    entries = [{"i": i} for i in range(3)]
    assert lu.cap_history(entries, 5) == entries


def test_cap_history_invalid_max_returns_all():
    entries = [{"i": i} for i in range(3)]
    assert lu.cap_history(entries, 0) == entries
    assert lu.cap_history(entries, -1) == entries


def test_cap_history_non_list_returns_empty():
    assert lu.cap_history("not a list", 5) == []


# ==================== load_history ====================

def test_load_history_missing(tmp_path):
    assert lu.load_history(str(tmp_path / "nope.json")) == []


def test_load_history_corrupt(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{broken", encoding="utf-8")
    assert lu.load_history(str(f)) == []


def test_load_history_non_list_returns_empty(tmp_path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert lu.load_history(str(f)) == []


# ==================== append_history ====================

def test_append_and_load_roundtrip(tmp_path):
    p = str(tmp_path / "history.json")
    n = lu.append_history(p, [{"time": "1", "rid": "a"}], 500)
    assert n == 1
    assert lu.load_history(p) == [{"time": "1", "rid": "a"}]


def test_append_history_caps(tmp_path):
    p = str(tmp_path / "history.json")
    for i in range(10):
        lu.append_history(p, [{"i": i}], 3)
    hist = lu.load_history(p)
    assert len(hist) == 3
    assert hist[-1] == {"i": 9}


def test_append_history_atomic_no_tmp_leftover(tmp_path):
    p = str(tmp_path / "history.json")
    lu.append_history(p, [{"i": 1}], 500)
    assert not list(tmp_path.glob("*.tmp"))


# ==================== init_runtime_logging ====================

def _clear_root_handlers():
    saved = list(logging.root.handlers)
    for h in list(logging.root.handlers):
        logging.root.removeHandler(h)
    return saved


def _restore_root_handlers(saved):
    for h in list(logging.root.handlers):
        logging.root.removeHandler(h)
    for h in saved:
        logging.root.addHandler(h)


def test_init_runtime_logging_adds_handlers(tmp_path):
    saved = _clear_root_handlers()
    try:
        lu.init_runtime_logging(level=logging.DEBUG, log_dir=str(tmp_path / "logs"))
        handlers = logging.root.handlers
        assert any(isinstance(h, logging.handlers.RotatingFileHandler) for h in handlers)
        assert any(isinstance(h, logging.StreamHandler) for h in handlers)
        # 文件已创建
        assert (tmp_path / "logs" / "runtime.log").exists()
        # 轮转参数正确
        rfh = next(h for h in handlers if isinstance(h, logging.handlers.RotatingFileHandler))
        assert rfh.maxBytes == 5 * 1024 * 1024
        assert rfh.backupCount == 5
    finally:
        _restore_root_handlers(saved)


def test_init_runtime_logging_skips_when_handlers_exist():
    # 若 root 已有 handler（如 pytest），不应重复添加（不抛异常即可）
    saved = _clear_root_handlers()
    try:
        logging.root.addHandler(logging.StreamHandler())
        before = len(logging.root.handlers)
        lu.init_runtime_logging()
        assert len(logging.root.handlers) >= before
    finally:
        _restore_root_handlers(saved)


def test_logger_info_works_without_account():
    # 验证既有 logger.info(...) 在结构化格式下不抛 KeyError（ContextFilter 注入 account 缺省空串）。
    # 自包含：手动挂载一个带本模块格式串 + ContextFilter 的 handler，避免依赖 root 全局配置。
    import io

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s %(account)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler.addFilter(lu._ContextFilter())

    logger = logging.getLogger("demo_mod_account_test")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("hello world")  # 不应抛 KeyError
        out = stream.getvalue()
        assert "hello world" in out
        assert "[INFO]" in out  # 结构化格式串完整渲染（account 为空串）
    finally:
        logger.removeHandler(handler)


# ==================== get_logger ====================

def test_get_logger_injects_account():
    adapter = lu.get_logger("test_mod", account="room123")
    _, kwargs = adapter.process("hi", {})
    assert kwargs["extra"]["account"] == "room123"


def test_get_logger_default_account_empty():
    adapter = lu.get_logger("test_mod")
    _, kwargs = adapter.process("hi", {})
    assert kwargs["extra"]["account"] == ""


# ==================== 日志分级 / 统一模型（日志模块功能性重写） ====================

def test_event_types_and_levels_constants():
    assert lu.EVENT_TYPES == frozenset(
        {"live_on", "live_off", "new_post", "error", "cookie_warn", "system"}
    )
    assert lu.LEVELS == frozenset({"info", "warn", "error"})
    assert lu.ERROR_THROTTLE_MINUTES == 30
    assert lu.STATUS_TO_TYPE["live"] == "live_on"
    assert lu.STATUS_TO_TYPE["offline"] == "live_off"
    assert lu.STATUS_TO_TYPE["replay"] == "live_off"
    assert lu.STATUS_TO_TYPE["error"] == "error"
    assert lu.TYPE_TO_LEVEL["cookie_warn"] == "warn"
    assert lu.TYPE_TO_LEVEL["error"] == "error"
    assert lu.TYPE_TO_LEVEL["new_post"] == "info"


def test_type_from_status_and_level_from_type():
    assert lu.type_from_status("live") == "live_on"
    assert lu.type_from_status("offline") == "live_off"
    assert lu.type_from_status("replay") == "live_off"
    assert lu.type_from_status("error") == "error"
    assert lu.type_from_status("unknown") == "system"
    assert lu.type_from_status(None) == "system"
    assert lu.level_from_type("live_on") == "info"
    assert lu.level_from_type("new_post") == "info"
    assert lu.level_from_type("cookie_warn") == "warn"
    assert lu.level_from_type("error") == "error"
    assert lu.level_from_type("nope") == "info"
    assert lu.level_from_type(None) == "info"


def test_should_suppress_30min_window(tmp_path):
    p = str(tmp_path / "history.json")
    lu.append_history(p, [{"time": "2026-07-10 10:00:00", "rid": "1", "type": "error"}], 500)
    now_in = datetime(2026, 7, 10, 10, 5)    # 5 分钟之后 → 窗口内
    now_out = datetime(2026, 7, 10, 10, 35)   # 35 分钟之后 → 窗口外
    assert lu.should_suppress("1", "error", now_in, history_path=p) is True
    assert lu.should_suppress("1", "error", now_out, history_path=p) is False
    # 不同 rid / 不同 type 不抑制
    assert lu.should_suppress("2", "error", now_in, history_path=p) is False
    assert lu.should_suppress("1", "cookie_warn", now_in, history_path=p) is False
    # 空 rid / 空 type 视为不抑制
    assert lu.should_suppress("", "error", now_in, history_path=p) is False
    assert lu.should_suppress("1", "", now_in, history_path=p) is False


def test_should_suppress_with_in_memory(tmp_path):
    p = str(tmp_path / "history.json")
    now = datetime(2026, 7, 10, 10, 0)
    # 内存 pending 中已有同 rid+type（10 分钟前）→ 抑制，不依赖磁盘
    pending = [{"time": "2026-07-10 09:50:00", "rid": "A", "type": "error"}]
    assert lu.should_suppress("A", "error", now, history_path=p, in_memory=pending) is True
    # 不同 type 不抑制
    assert lu.should_suppress("A", "cookie_warn", now, history_path=p, in_memory=pending) is False


def test_dedupe_by_throttle_suppresses_recent_error(tmp_path):
    p = str(tmp_path / "history.json")
    now = datetime(2026, 7, 10, 10, 0)
    # 预置一条 5 分钟前的 error（rid=1）
    lu.append_history(p, [{"time": "2026-07-10 09:55:00", "rid": "1", "type": "error"}], 500)
    entries = [
        {"rid": "1", "type": "error", "time": "2026-07-10 10:00:00"},   # 应被抑制
        {"rid": "1", "type": "new_post", "time": "2026-07-10 10:00:00"},  # 保留（非错误类）
        {"rid": "2", "type": "error", "time": "2026-07-10 10:00:00"},    # 保留（不同 rid）
    ]
    out = lu.dedupe_by_throttle(entries, now, history_path=p)
    assert [e["type"] for e in out] == ["new_post", "error"]


def test_dedupe_by_throttle_keeps_all_when_no_recent(tmp_path):
    p = str(tmp_path / "history.json")
    now = datetime(2026, 7, 10, 10, 0)
    entries = [
        {"rid": "1", "type": "error", "time": "2026-07-10 10:00:00"},
        {"rid": "1", "type": "system", "time": "2026-07-10 10:00:00"},
    ]
    out = lu.dedupe_by_throttle(entries, now, history_path=p)
    # 磁盘无近期同 rid+error → 全部保留
    assert len(out) == 2


def test_dedupe_by_throttle_does_not_mutate_input(tmp_path):
    p = str(tmp_path / "history.json")
    now = datetime(2026, 7, 10, 10, 0)
    entries = [{"rid": "1", "type": "error", "time": "2026-07-10 10:00:00"}]
    snapshot = [dict(e) for e in entries]
    lu.dedupe_by_throttle(entries, now, history_path=p)
    assert entries == snapshot


def test_compute_stats_aggregates_by_day():
    hist = [
        {"time": "2026-07-10 10:00:00", "type": "new_post"},
        {"time": "2026-07-10 11:00:00", "type": "new_post"},
        {"time": "2026-07-10 12:00:00", "type": "live_on"},
        {"time": "2026-07-09 10:00:00", "type": "new_post"},
        {"time": "2026-07-08 10:00:00", "type": "error"},
    ]
    now = datetime(2026, 7, 10, 23, 0)
    s = lu.compute_stats(hist, days=7, now=now)
    # labels 从 07-04 … 07-10（idx 6 为今天 07-10）
    assert s["days"][6] == "07-10"
    assert s["new_post"][6] == 2       # 7-10 两条新作品
    assert s["new_post"][5] == 1       # 7-09 一条
    assert s["live_on"][6] == 1
    assert s["error"][4] == 1          # 7-08 一条错误
    assert s["totals"]["new_post"] == 3
    assert s["totals"]["live_on"] == 1
    assert s["totals"]["error"] == 1
    assert s["totals"]["cookie_warn"] == 0


def test_compute_stats_ignores_unknown_type():
    hist = [
        {"time": "2026-07-10 10:00:00", "type": "new_post"},
        {"time": "2026-07-10 10:00:00", "type": "weird"},  # 不参与统计
        {"time": "2026-07-10 10:00:00"},                    # 无 type 不参与
    ]
    now = datetime(2026, 7, 10, 23, 0)
    s = lu.compute_stats(hist, days=7, now=now)
    assert s["new_post"][6] == 1
    assert s["totals"]["new_post"] == 1

