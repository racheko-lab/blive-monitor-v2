"""push_utils 单元测试：配置解析、分发路由、各渠道发送（mock 网络）。"""
import json
import urllib.request

import pytest

import push_utils


class FakeResp:
    """模拟 urllib 响应（上下文管理器 + read()）。"""

    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(payload):
    """返回一个可被 monkeypatch 的 urlopen 替身。"""

    def _fake(req, timeout=10):
        return FakeResp(payload)

    return _fake


# ==================== load_push_cfg ====================

def test_load_push_cfg_empty():
    assert push_utils.load_push_cfg("") == {}
    assert push_utils.load_push_cfg("{}") == {}


def test_load_push_cfg_legacy_sendkey():
    cfg = push_utils.load_push_cfg('{"sendkey": "SCT123"}')
    assert cfg == {"type": "serverchan", "sendkey": "SCT123"}


def test_load_push_cfg_legacy_fallback():
    cfg = push_utils.load_push_cfg("{}", fallback_sendkey="SCT999")
    assert cfg == {"type": "serverchan", "sendkey": "SCT999"}


def test_load_push_cfg_bark():
    cfg = push_utils.load_push_cfg('{"push": {"type": "bark", "url": "https://api.day.app/KEY", "group": "blive"}}')
    assert cfg["type"] == "bark"
    assert cfg["url"] == "https://api.day.app/KEY"
    assert cfg["group"] == "blive"


def test_load_push_cfg_wecom():
    cfg = push_utils.load_push_cfg('{"push": {"type": "wecom", "webhook": "https://qyapi.weixin.qq.com/xxx"}}')
    assert cfg["type"] == "wecom"
    assert cfg["webhook"].startswith("https://qyapi")


def test_load_push_cfg_pushplus():
    cfg = push_utils.load_push_cfg('{"push": {"type": "pushplus", "token": "pp-token"}}')
    assert cfg["type"] == "pushplus"
    assert cfg["token"] == "pp-token"


def test_load_push_cfg_telegram():
    cfg = push_utils.load_push_cfg('{"push": {"type": "telegram", "token": "T", "chat": "C"}}')
    assert cfg["type"] == "telegram"
    assert cfg["token"] == "T" and cfg["chat"] == "C"


def test_load_push_cfg_invalid_json():
    # 解析失败应回退为未配置（不抛异常）
    assert push_utils.load_push_cfg("{not json") == {}


# ==================== dispatch_push 路由 ====================

def test_dispatch_push_empty():
    assert push_utils.dispatch_push({}, "t", "d") is False


def test_dispatch_push_unknown_type(caplog):
    assert push_utils.dispatch_push({"type": "nope"}, "t", "d") is False


def test_dispatch_push_routes_serverchan(monkeypatch):
    called = {}

    def fake(req, timeout=10):
        called["url"] = req.full_url
        return FakeResp({"code": 0})

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    ok = push_utils.dispatch_push({"type": "serverchan", "sendkey": "SCT1"}, "标题", "正文")
    assert ok is True
    assert "sctapi.ftqq.com" in called["url"]


def test_dispatch_push_routes_bark(monkeypatch):
    captured = {}

    def fake(req, timeout=10):
        captured["url"] = req.full_url
        captured["data"] = req.data
        return FakeResp({"code": 200})

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    ok = push_utils.dispatch_push(
        {"type": "bark", "url": "https://api.day.app/KEY", "group": "blive"},
        "🔴 开播", "正文",
    )
    assert ok is True
    assert captured["url"] == "https://api.day.app/KEY"
    body = json.loads(captured["data"])
    assert body["title"] == "🔴 开播"
    assert body["group"] == "blive"


# ==================== 单渠道发送 ====================

def test_send_via_serverchan_ok(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen({"code": 0}))
    assert push_utils.send_via_serverchan("SCT1", "t", "d") is True


def test_send_via_serverchan_fail_code(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen({"code": 1, "msg": "x"}))
    assert push_utils.send_via_serverchan("SCT1", "t", "d") is False


def test_send_via_serverchan_empty_key():
    assert push_utils.send_via_serverchan("", "t", "d") is False


def test_send_via_wecom_ok(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen({"errcode": 0}))
    assert push_utils.send_via_wecom("https://qyapi.weixin.qq.com/x", "t", "d") is True


def test_send_via_wecom_fail(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen({"errcode": 93000}))
    assert push_utils.send_via_wecom("https://qyapi.weixin.qq.com/x", "t", "d") is False


def test_send_via_pushplus_ok(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen({"code": 200}))
    assert push_utils.send_via_pushplus("tok", "t", "d") is True


def test_send_via_bark_ok(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen({"code": 200}))
    assert push_utils.send_via_bark("https://api.day.app/KEY", "t", "d", group="g") is True


def test_send_via_bark_empty():
    assert push_utils.send_via_bark("", "t", "d") is False


def test_send_via_bark_network_error(monkeypatch):
    def boom(req, timeout=10):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert push_utils.send_via_bark("https://api.day.app/KEY", "t", "d") is False


def test_send_via_telegram_ok(monkeypatch):
    captured = {}

    def fake(req, timeout=10):
        captured["req"] = req
        return FakeResp({"ok": True, "result": {}})

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert push_utils.send_via_telegram("T", "C", "标题", "正文") is True
    # 应为 POST + JSON，而非把消息塞进 URL 查询串
    assert captured["req"].data is not None
    body = json.loads(captured["req"].data)
    assert body["chat_id"] == "C"
    assert "标题" in body["text"]
    assert "正文" in body["text"]


def test_send_via_telegram_long_message(monkeypatch):
    """长消息（远超 URL 长度上限）也能通过 POST 体发送。"""
    captured = {}

    def fake(req, timeout=10):
        captured["req"] = req
        return FakeResp({"ok": True, "result": {}})

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    long_text = "描述：" + "非常长的内容" * 500
    assert push_utils.send_via_telegram("T", "C", "🆕 新作品", long_text) is True
    body = json.loads(captured["req"].data)
    assert long_text in body["text"]


def test_send_via_telegram_empty():
    assert push_utils.send_via_telegram("", "C", "t", "d") is False
    assert push_utils.send_via_telegram("T", "", "t", "d") is False
