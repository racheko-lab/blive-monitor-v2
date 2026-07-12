"""P0-2 通知可靠性回归测试：重试 / 失败分类 / 退避时序 / 去重安全 / 兼容契约。

覆盖 push_utils 的 SendResult + send_with_retry + is_retryable，以及
dispatch_push(返回 SendResult) 与 dispatch_push_ok(返回 bool) 的契约。
"""
import json
import urllib.request
import urllib.error

import pytest

import push_utils
import notify_dedup


class _FakeResp:
    """模拟 urllib 响应（上下文管理器 + read()）。"""

    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ==================== 1. 瞬时失败第 2 次成功 ====================

def test_retry_then_success(monkeypatch):
    """第一次失败（可重试）、第二次成功 → ok=True 且 attempts=2。"""
    state = {"n": 0}

    def fake_send(title, desp):
        state["n"] += 1
        if state["n"] == 1:
            return push_utils.SendResult(
                ok=False, attempts=1, last_error="URLError: transient", status_code=None)
        return push_utils.SendResult(ok=True, attempts=1, last_error="", status_code=None)

    # 不实际 sleep
    monkeypatch.setattr(push_utils.time, "sleep", lambda s: None)

    res = push_utils.send_with_retry(fake_send, "t", "d")
    assert res.ok is True
    assert res.attempts == 2
    assert state["n"] == 2  # 确实发了 2 次（含 1 次重试）


# ==================== 2. 4xx 鉴权失败不重试 ====================

def test_auth_4xx_no_retry(monkeypatch):
    """4xx 鉴权失败 → 不重试（attempts=1, ok=False）。"""
    state = {"n": 0}

    def fake_send(title, desp):
        state["n"] += 1
        return push_utils.SendResult(
            ok=False, attempts=1, last_error="HTTP 401", status_code=401)

    monkeypatch.setattr(push_utils.time, "sleep", lambda s: None)

    res = push_utils.send_with_retry(fake_send, "t", "d")
    assert res.ok is False
    assert res.attempts == 1
    assert state["n"] == 1
    assert res.status_code == 401


# ==================== 3. 退避时序 2/4/8 ====================

def test_backoff_sequence(monkeypatch):
    """多次重试时 time.sleep 按 2/4/8 调用（base_delay * 2**(i-1)）。"""
    sleeps = []

    def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(push_utils.time, "sleep", fake_sleep)

    def fake_send(title, desp):
        return push_utils.SendResult(
            ok=False, attempts=1, last_error="URLError: net", status_code=None)

    # max_attempts=4 → 3 次退避：2, 4, 8（最后一次不 sleep）
    res = push_utils.send_with_retry(fake_send, "t", "d", max_attempts=4, base_delay=2)
    assert res.ok is False
    assert res.attempts == 4
    assert sleeps == [2, 4, 8]


def test_is_retryable_classification():
    """失败分类：5xx/429/网络→重试；4xx/业务拒绝/配置缺失→放弃。"""
    # 可重试
    assert push_utils.is_retryable(500, "HTTP 500") is True
    assert push_utils.is_retryable(429, "HTTP 429") is True
    assert push_utils.is_retryable(None, "URLError: timeout") is True
    assert push_utils.is_retryable(None, "error: socket.timeout") is True
    # 不可重试
    assert push_utils.is_retryable(401, "HTTP 401") is False
    assert push_utils.is_retryable(403, "HTTP 403") is False
    assert push_utils.is_retryable(400, "HTTP 400") is False
    assert push_utils.is_retryable(None, "biz_reject: errcode=93000") is False
    assert push_utils.is_retryable(None, "config: empty webhook") is False


# ==================== 4. 去重安全（重试后成功，record 仅一次） ====================

def test_dedup_safe_on_retry_success(monkeypatch):
    """模拟「重试后成功」：dispatch_push 内部重试 1 次，但调用方仅 record 1 次。"""
    state = {"calls": 0}

    def fake_urlopen(req, timeout=10):
        state["calls"] += 1
        if state["calls"] == 1:
            # 第一次瞬时网络错误（可重试）
            raise urllib.error.URLError("transient network")
        return _FakeResp({"errcode": 0})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(push_utils.time, "sleep", lambda s: None)

    # record 计数：验证调用方仅最终成功时记一次
    records = {"n": 0}
    monkeypatch.setattr(
        notify_dedup, "record",
        lambda key, now=None: records.__setitem__("n", records["n"] + 1),
    )

    res = push_utils.dispatch_push({"type": "wecom", "webhook": "http://x"}, "t", "d")
    assert res.ok is True
    assert state["calls"] == 2  # 确实发生了 2 次发送（含 1 次重试）

    # 调用方逻辑：仅最终成功才 record（去重账本安全：重试不重复 record）
    if res.ok:
        notify_dedup.record("live:douyin_foo")
    assert records["n"] == 1


# ==================== 5. 兼容契约 ====================

def test_dispatch_push_returns_sendresult(monkeypatch):
    """dispatch_push 返回 SendResult 且含 attempts / status_code。"""
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=10: _FakeResp({"errcode": 0}),
    )
    res = push_utils.dispatch_push({"type": "wecom", "webhook": "http://x"}, "t", "d")
    assert isinstance(res, push_utils.SendResult)
    assert res.ok is True
    assert res.attempts >= 1
    assert res.status_code is None


def test_dispatch_push_ok_returns_bool(monkeypatch):
    """dispatch_push_ok 返回 bool（成功 True / 4xx 失败 False）。"""
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=10: _FakeResp({"errcode": 0}),
    )
    assert push_utils.dispatch_push_ok({"type": "wecom", "webhook": "http://x"}, "t", "d") is True

    # 4xx 鉴权失败 → 不重试 → 返回 bool False
    def fake_401(req, timeout=10):
        raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_401)
    assert push_utils.dispatch_push_ok({"type": "wecom", "webhook": "http://x"}, "t", "d") is False


def test_dispatch_push_empty_and_unknown(monkeypatch):
    """未配置 / 未知渠道返回 ok=False 的 SendResult（不抛异常）。"""
    assert push_utils.dispatch_push({}, "t", "d").ok is False
    assert push_utils.dispatch_push({"type": "nope"}, "t", "d").ok is False
