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
    assert push_utils.dispatch_push({}, "t", "d").ok is False


def test_dispatch_push_unknown_type(caplog):
    assert push_utils.dispatch_push({"type": "nope"}, "t", "d").ok is False


def test_dispatch_push_routes_serverchan(monkeypatch):
    called = {}

    def fake(req, timeout=10):
        called["url"] = req.full_url
        return FakeResp({"code": 0})

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    ok = push_utils.dispatch_push({"type": "serverchan", "sendkey": "SCT1"}, "标题", "正文")
    assert ok.ok is True
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
    assert ok.ok is True
    assert captured["url"] == "https://api.day.app/KEY"
    body = json.loads(captured["data"])
    assert body["title"] == "🔴 开播"
    assert body["group"] == "blive"


# ==================== 单渠道发送 ====================

def test_send_via_serverchan_ok(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen({"code": 0}))
    assert push_utils.send_via_serverchan("SCT1", "t", "d").ok is True


def test_send_via_serverchan_fail_code(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen({"code": 1, "msg": "x"}))
    assert push_utils.send_via_serverchan("SCT1", "t", "d").ok is False


def test_send_via_serverchan_empty_key():
    assert push_utils.send_via_serverchan("", "t", "d").ok is False


def test_send_via_wecom_ok(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen({"errcode": 0}))
    assert push_utils.send_via_wecom("https://qyapi.weixin.qq.com/x", "t", "d").ok is True


def test_send_via_wecom_fail(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen({"errcode": 93000}))
    assert push_utils.send_via_wecom("https://qyapi.weixin.qq.com/x", "t", "d").ok is False


def test_send_via_pushplus_ok(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen({"code": 200}))
    assert push_utils.send_via_pushplus("tok", "t", "d").ok is True


def test_send_via_bark_ok(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen({"code": 200}))
    assert push_utils.send_via_bark("https://api.day.app/KEY", "t", "d", group="g").ok is True


def test_send_via_bark_empty():
    assert push_utils.send_via_bark("", "t", "d").ok is False


def test_send_via_bark_network_error(monkeypatch):
    def boom(req, timeout=10):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert push_utils.send_via_bark("https://api.day.app/KEY", "t", "d").ok is False


def test_send_via_telegram_ok(monkeypatch):
    captured = {}

    def fake(req, timeout=10):
        captured["req"] = req
        return FakeResp({"ok": True, "result": {}})

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert push_utils.send_via_telegram("T", "C", "标题", "正文").ok is True
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
    assert push_utils.send_via_telegram("T", "C", "🆕 新作品", long_text).ok is True
    body = json.loads(captured["req"].data)
    assert long_text in body["text"]


def test_send_via_telegram_empty():
    assert push_utils.send_via_telegram("", "C", "t", "d").ok is False
    assert push_utils.send_via_telegram("T", "", "t", "d").ok is False


# ==================== P0-3 通知精细化：decorate 注入矩阵 ====================

def test_decorate_wecom_mention_multiple():
    """wecom：多提及逗号分隔 -> <@zhangsan> <@lisi> 出现在 desp 开头。"""
    _, desp = push_utils.decorate("标题", "正文", {"type": "wecom", "mention": "zhangsan,lisi"})
    assert desp.startswith("<@zhangsan> <@lisi>\n正文")


def test_decorate_wecom_mention_whitespace_and_empty_tokens():
    """wecom：空白/空项被跳过，仅有效 token 被包裹。"""
    _, desp = push_utils.decorate("t", "正文", {"type": "wecom", "mention": " a , , b "})
    assert desp == "<@a> <@b>\n正文"


def test_decorate_telegram_mention_autoprefix():
    """telegram：无 @ 时自动补 @，拼到 desp 开头。"""
    _, desp = push_utils.decorate("t", "正文", {"type": "telegram", "mention": "username"})
    assert desp.startswith("@username\n正文")


def test_decorate_telegram_mention_keeps_existing_at():
    """telegram：已有 @ 的 token 不重复补 @。"""
    _, desp = push_utils.decorate("t", "正文", {"type": "telegram", "mention": "@bob,carol"})
    assert desp.startswith("@bob @carol\n正文")


def test_decorate_bark_mention_ignored_title_unchanged():
    """bark：mention 被忽略、group 不进入 title（走原生参数）。"""
    title, desp = push_utils.decorate(
        "🔴 开播", "正文", {"type": "bark", "mention": "alice", "group": "blive"}
    )
    assert title == "🔴 开播"        # title 不变
    assert "alice" not in desp        # mention 忽略


def test_decorate_serverchan_mention_ignored_group_prefix():
    """serverchan：mention 忽略，group 前缀 [x] 加到 title。"""
    title, desp = push_utils.decorate(
        "开播", "正文", {"type": "serverchan", "mention": "x", "group": "B站"}
    )
    assert title == "[B站] 开播"
    assert "x" not in desp


def test_decorate_pushplus_mention_ignored_group_prefix():
    """pushplus：mention 忽略，group 前缀 [x] 加到 title。"""
    title, desp = push_utils.decorate(
        "开播", "正文", {"type": "pushplus", "mention": "x", "group": "B站"}
    )
    assert title == "[B站] 开播"
    assert "x" not in desp


def test_decorate_group_prefix_non_bark():
    """非 Bark 渠道：group 非空时 title 加 [分组名] 前缀。"""
    title, _ = push_utils.decorate("标题", "正文", {"type": "wecom", "group": "直播"})
    assert title == "[直播] 标题"


def test_decorate_bark_group_no_title_prefix():
    """bark：即便配置 group，title 也不加前缀（走原生参数）。"""
    title, _ = push_utils.decorate("标题", "正文", {"type": "bark", "group": "直播"})
    assert title == "标题"


def test_decorate_empty_mention_group_noop():
    """空 mention/group：等价于无装饰，原值返回。"""
    title, desp = push_utils.decorate(
        "标题", "正文", {"type": "wecom", "mention": "", "group": ""}
    )
    assert title == "标题" and desp == "正文"


def test_decorate_exception_input_safe():
    """异常输入（push_cfg.get 抛错）：返回原值，绝不抛出。"""

    class BadDict:
        def get(self, *a, **k):
            raise RuntimeError("bad")

    title, desp = push_utils.decorate("标题", "正文", BadDict())
    assert title == "标题" and desp == "正文"


def test_decorate_mention_single_injection_multiline():
    """mention 仅注入一次（整条消息级），不逐行重复。"""
    desp = "line1\nline2"
    _, out = push_utils.decorate("t", desp, {"type": "wecom", "mention": "a,b"})
    assert out == "<@a> <@b>\nline1\nline2"


def test_dispatch_push_wecom_mention_and_group(monkeypatch):
    """集成：wecom 经 dispatch_push 后 content 含 group 前缀 + mention 注入。"""
    captured = {}

    def fake(req, timeout=10):
        captured["data"] = req.data
        return FakeResp({"errcode": 0})

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    cfg = {
        "type": "wecom",
        "webhook": "https://qyapi.weixin.qq.com/x",
        "mention": "zhangsan,lisi",
        "group": "B站",
    }
    ok = push_utils.dispatch_push(cfg, "🔴 x 开播了！", "正文")
    assert ok.ok is True
    body = json.loads(captured["data"])
    content = body["text"]["content"]
    assert content.startswith("[B站] 🔴 x 开播了！\n\n<@zhangsan> <@lisi>\n正文")


def test_dispatch_push_telegram_mention_and_group(monkeypatch):
    """集成：telegram 经 dispatch_push 后 text 含 group 前缀 + @提及。"""
    captured = {}

    def fake(req, timeout=10):
        captured["data"] = req.data
        return FakeResp({"ok": True, "result": {}})

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    cfg = {
        "type": "telegram",
        "token": "T",
        "chat": "C",
        "mention": "username",
        "group": "直播",
    }
    ok = push_utils.dispatch_push(cfg, "标题", "正文")
    assert ok.ok is True
    body = json.loads(captured["data"])
    assert body["text"].startswith("[直播] 标题\n\n@username\n正文")


def test_dispatch_push_bark_mention_ignored_group_param(monkeypatch):
    """集成：bark 的 group 走参数、title 无前缀、mention 被忽略。"""
    captured = {}

    def fake(req, timeout=10):
        captured["data"] = req.data
        return FakeResp({"code": 200})

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    cfg = {
        "type": "bark",
        "url": "https://api.day.app/KEY",
        "mention": "@alice",
        "group": "blive",
    }
    ok = push_utils.dispatch_push(cfg, "开播了", "正文")
    assert ok.ok is True
    body = json.loads(captured["data"])
    assert body["title"] == "开播了"   # 不带 group 前缀
    assert body["group"] == "blive"    # 走原生参数
    assert "@alice" not in body["body"]


def test_dispatch_push_serverchan_group_prefix_mention_ignored(monkeypatch):
    """集成：serverchan group 前缀到 title，mention 不进入 desp。"""
    from urllib.parse import parse_qs

    captured = {}

    def fake(req, timeout=10):
        captured["data"] = req.data
        return FakeResp({"code": 0})

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    cfg = {"type": "serverchan", "sendkey": "SCT1", "mention": "ignored", "group": "B站"}
    ok = push_utils.dispatch_push(cfg, "开播", "正文")
    assert ok.ok is True
    parsed = parse_qs(captured["data"].decode("utf-8"))
    assert parsed["title"][0] == "[B站] 开播"
    assert "ignored" not in parsed["desp"][0]


def test_dispatch_push_pushplus_group_prefix_mention_ignored(monkeypatch):
    """集成：pushplus group 前缀到 title，mention 不进入 content。"""
    from urllib.parse import parse_qs

    captured = {}

    def fake(req, timeout=10):
        captured["data"] = req.data
        return FakeResp({"code": 200})

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    cfg = {"type": "pushplus", "token": "tok", "mention": "ignored", "group": "B站"}
    ok = push_utils.dispatch_push(cfg, "开播", "正文")
    assert ok.ok is True
    parsed = parse_qs(captured["data"].decode("utf-8"))
    assert parsed["title"][0] == "[B站] 开播"
    assert "ignored" not in parsed["content"][0]


def test_dispatch_push_no_mention_group_backward_compat(monkeypatch):
    """向后兼容：无 mention/group 的配置行为完全不变。"""
    captured = {}

    def fake(req, timeout=10):
        captured["data"] = req.data
        return FakeResp({"errcode": 0})

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    ok = push_utils.dispatch_push(
        {"type": "wecom", "webhook": "https://qyapi.weixin.qq.com/x"}, "标题", "正文"
    )
    assert ok.ok is True
    body = json.loads(captured["data"])
    assert body["text"]["content"] == "标题\n\n正文"

