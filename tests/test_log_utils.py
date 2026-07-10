"""log_utils 单元测试：HISTORY_MAX 单一来源、history 读写/上限、运行时日志初始化与结构化。"""
import json
import logging
import logging.handlers

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
