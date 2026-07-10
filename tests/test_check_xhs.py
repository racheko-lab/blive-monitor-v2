#!/usr/bin/env python3
"""小红书直播检测的单测（离线，不依赖真实网络）。

覆盖 parse_xiaohongshu_live 的各类输入，以及 fetch_xiaohongshu 的网络异常降级。
真实站点的 __INITIAL_STATE__ 字段形态可能随版本变化，需用户用真实账号跑一轮后微调。
"""
import json

import check_status as cs


def _wrap_initial_state(obj: dict) -> str:
    """构造带 window.__INITIAL_STATE__ 的小红书主页 HTML 片段。"""
    return (
        '<html><head><title>某用户 - 小红书</title></head><body>'
        f'<script>window.__INITIAL_STATE__={json.dumps(obj, ensure_ascii=False)};</script>'
        "</body></html>"
    )


def test_parse_offline_no_signal():
    html = '<html><head><title>某用户 - 小红书</title></head><body>普通主页，无直播</body></html>'
    r = cs.parse_xiaohongshu_live(html)
    assert r["status"] == "offline"
    assert r["live_url"] == ""


def test_parse_anti_bot_treated_as_offline():
    html = '<html><body>请完成安全验证，滑动验证以继续访问</body></html>'
    r = cs.parse_xiaohongshu_live(html)
    assert r["status"] == "offline"


def test_parse_live_via_initial_state():
    html = _wrap_initial_state({
        "user": {"nickname": "测试用户"},
        "liveRoom": {"liveStatus": 1, "roomId": "abc123", "title": "今晚吃啥直播"},
    })
    r = cs.parse_xiaohongshu_live(html)
    assert r["status"] == "live"
    assert r["title"] == "今晚吃啥直播"
    assert "abc123" in r["live_url"]
    assert r["live_url"].startswith("https://live.xiaohongshu.com/room/")


def test_parse_live_via_initial_state_nested():
    # liveRoom 嵌套在更深层结构里，递归应能找到
    html = _wrap_initial_state({
        "user": {"nickname": "测试用户", "liveRoom": {"liveStatus": 1, "roomId": "room99"}},
    })
    r = cs.parse_xiaohongshu_live(html)
    assert r["status"] == "live"
    assert "room99" in r["live_url"]


def test_parse_live_offline_status_in_state():
    # liveRoom 存在但 liveStatus 明确离线 -> 不应判为 live
    html = _wrap_initial_state({
        "liveRoom": {"liveStatus": 4, "roomId": "abc123"},
    })
    r = cs.parse_xiaohongshu_live(html)
    assert r["status"] == "offline"


def test_parse_live_via_room_link():
    html = (
        '<html><head><title>某用户 - 小红书</title></head><body>'
        '<a href="https://live.xiaohongshu.com/room/xyz789">直播中</a>'
        "</body></html>"
    )
    r = cs.parse_xiaohongshu_live(html)
    assert r["status"] == "live"
    assert "xyz789" in r["live_url"]


def test_parse_live_text_fallback():
    html = '<html><head><title>某用户 - 小红书</title></head><body>该用户正在直播</body></html>'
    r = cs.parse_xiaohongshu_live(html)
    assert r["status"] == "live"


def test_fetch_network_error_does_not_raise(monkeypatch):
    """抓取失败应安全降级为 offline（保证恢复开播时 offline->live 仍能推送）。"""

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(cs, "fetch_with_retry", _boom)
    r = cs.fetch_xiaohongshu("some_uid")
    assert r["status"] == "offline"
    assert r["live_url"] == "https://www.xiaohongshu.com/user/profile/some_uid"


def test_main_xhs_live_triggers_push(monkeypatch, tmp_path):
    """端到端：rooms.json 里 xhs 房间开播时，main() 应触发推送并落地状态。"""
    # 重定向状态文件到临时目录，避免污染仓库
    monkeypatch.setattr(cs, "ROOMS_FILE", str(tmp_path / "rooms.json"))
    monkeypatch.setattr(cs, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(cs, "STATUS_FILE", str(tmp_path / "status.json"))
    monkeypatch.setattr(cs, "TRACKING_FILE", str(tmp_path / "tracking.json"))
    monkeypatch.setattr(cs, "HISTORY_FILE", str(tmp_path / "history.json"))
    (tmp_path / "rooms.json").write_text(
        json.dumps([{"platform": "xhs", "id": "test_xhs_uid", "name": "小红书测试号"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cs,
        "fetch_xiaohongshu",
        lambda uid: {
            "status": "live",
            "title": "测试直播",
            "online": 100,
            "live_url": "https://live.xiaohongshu.com/room/room1",
            "nickname": "",
            "time": "",
        },
    )
    calls = []
    monkeypatch.setattr(cs, "dispatch_push", lambda cfg, t, d: calls.append((t, d)) or True)
    monkeypatch.setenv("BLIVE_CONFIG", '{"push": {"type": "bark", "key": "x"}}')

    cs.main()

    assert len(calls) == 1
    title, desp = calls[0]
    assert "小红书" in title or "小红书" in desp
    assert "https://live.xiaohongshu.com/room/room1" in desp
    st = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert st.get("xhs_test_xhs_uid") == "live"


def _wrap_real_format(obj: dict) -> str:
    """构造小红书真实内联格式：JSON 经 HTML 转义，并掺入 JS 字面量 undefined。

    真实站点的 __INITIAL_STATE__ 正是此形态（&quot; 转义 + undefined），
    解析器必须能稳健处理，否则会退化成脆弱的关键词兜底。
    """
    import html as _html

    raw = json.dumps(obj, ensure_ascii=False)
    # 模拟真实页面：把对象里某字段设为 undefined（json 不支持，需手动注入）
    raw = raw.replace('"__UNDEF__"', "undefined")
    escaped = _html.escape(raw)
    return (
        '<html><head><title>某用户 - 小红书</title></head><body>'
        f'<script>window.__INITIAL_STATE__ = {escaped};</script>'
        "</body></html>"
    )


def test_parse_real_format_with_undefined_and_escape():
    # 真实页面：liveRoom 嵌套在 user 下，含 undefined 字段，整体 HTML 转义
    html = _wrap_real_format({
        "user": {
            "nickname": "真实主播",
            "liveRoom": {"liveStatus": 1, "roomId": "r999", "title": "开播啦"},
            "someUndefinedField": "__UNDEF__",
        },
        "global": {"x": "__UNDEF__"},
    })
    r = cs.parse_xiaohongshu_live(html)
    assert r["status"] == "live"
    assert r["title"] == "开播啦"
    assert "r999" in r["live_url"]
    assert r["nickname"] == "真实主播"


def test_parse_real_format_ended_offline():
    html = _wrap_real_format({
        "user": {"nickname": "真实主播", "liveRoom": {"liveStatus": 4, "roomId": "r999"}},
    })
    r = cs.parse_xiaohongshu_live(html)
    assert r["status"] == "offline"


def test_parse_real_format_nested_undefined_offline():
    # 未开播主页：__INITIAL_STATE__ 存在但无 liveRoom（真实未开播形态）
    html = _wrap_real_format({
        "user": {"nickname": "真实主播", "someUndefinedField": "__UNDEF__"},
        "global": {"x": "__UNDEF__"},
    })
    r = cs.parse_xiaohongshu_live(html)
    assert r["status"] == "offline"
    assert r["live_url"] == ""


# ===== 无头浏览器渲染后的直播间 DOM 检测（真实可用路径）=====


def _wrap_room_dom(live: bool, title: str = "测试主播") -> str:
    """构造渲染后的直播间 DOM 片段。live=True 时带 xgplayer-is-live 播放器。"""
    player = (
        '<div class="player-el xgplayer xhsplayer-skin-live xgplayer-is-live xgplayer-playing"></div>'
        if live else '<div class="player-el xgplayer"></div>'
    )
    return (
        f'<html><head><title>{title}{cs.XHS_LIVE_TITLE_SUFFIX}</title></head>'
        f"<body>{player}</body></html>"
    )


def test_parse_room_dom_live_detected():
    # xgplayer-is-live 出现 -> live，并提取昵称（标题去掉后缀）
    r = cs.parse_xiaohongshu_room_dom(_wrap_room_dom(True, "太阳蛋本蛋🍳"), "https://live.xiaohongshu.com/room/abc")
    assert r["status"] == "live"
    assert r["nickname"] == "太阳蛋本蛋🍳"
    assert "live.xiaohongshu.com/room/" in r["live_url"]


def test_parse_room_dom_xhsplayer_skin_live():
    # xhsplayer-skin-live 也是在播信号
    html = '<html><head><title>某主播的小红书直播间</title></head><body><div class="xhsplayer-skin-live"></div></body></html>'
    r = cs.parse_xiaohongshu_room_dom(html, "https://xhslink.com/m/xyz")
    assert r["status"] == "live"
    assert r["nickname"] == "某主播"


def test_parse_room_dom_offline():
    # 无在播信号 -> offline
    r = cs.parse_xiaohongshu_room_dom(_wrap_room_dom(False, "测试主播"), "https://xhslink.com/m/xyz")
    assert r["status"] == "offline"
    assert r["live_url"] == ""


def test_parse_room_dom_risk_blocked_is_error_not_offline():
    # 数据中心 IP 风控页（安全验证/滑块/captcha 等）→ error，绝不能误判 offline 漏推
    html = (
        '<html><head><title>小红书</title></head>'
        '<body><div class="captcha-box">请完成安全验证，滑动验证以继续访问</div></body></html>'
    )
    r = cs.parse_xiaohongshu_room_dom(html, "https://xhslink.com/m/xyz")
    assert r["status"] == "error"
    assert r["live_url"] == ""


def test_parse_room_dom_xgplayer_playing_fallback_live():
    # 仅 xgplayer-playing（无 is-live/skin-live 字面量时）也应判为 live（抗 class 微调）
    html = (
        '<html><head><title>某主播的小红书直播间</title></head>'
        '<body><div class="xgplayer xgplayer-playing"></div></body></html>'
    )
    r = cs.parse_xiaohongshu_room_dom(html, "https://live.xiaohongshu.com/room/abc")
    assert r["status"] == "live"
    assert r["nickname"] == "某主播"


def test_fetch_xhs_shortlink_invalid_returns_error(monkeypatch):
    """短链失效（404/站外/异常）→ 本轮判 error 而非 offline，避免误标下播。"""
    monkeypatch.setattr(cs, "_resolve_xhs_shortlink",
                        lambda t: (t, False))
    # 短链失败时根本不应进入渲染（省一次 chromium 调用）
    called = {"n": 0}
    monkeypatch.setattr(cs, "_render_with_chromium", lambda u: called.__setitem__("n", called["n"] + 1) or "")
    r = cs.fetch_xiaohongshu("https://xhslink.com/m/dead")
    assert r["status"] == "error"
    assert called["n"] == 0  # 未渲染，直接判定失效


def test_fetch_xhs_no_chromium_degrades_offline(monkeypatch):
    """短链有效但无 chromium → 服务端无直播状态，安全降级 offline（不崩溃）。"""
    monkeypatch.setattr(cs, "_resolve_xhs_shortlink",
                        lambda t: ("https://live.xiaohongshu.com/room/abc", True))
    monkeypatch.setattr(cs, "_render_with_chromium", lambda u: None)
    r = cs.fetch_xiaohongshu("https://xhslink.com/m/ok")
    assert r["status"] == "offline"
    assert r["live_url"] == "https://live.xiaohongshu.com/room/abc"


def test_fetch_xhs_shortlink_valid_renders_and_reports_dom(monkeypatch):
    """短链有效 + 有 chromium → 进入 DOM 解析（live/offline/error 由渲染结果决定）。"""
    monkeypatch.setattr(cs, "_resolve_xhs_shortlink",
                        lambda t: ("https://live.xiaohongshu.com/room/abc", True))
    monkeypatch.setattr(cs, "_render_with_chromium",
                        lambda u: _wrap_room_dom(True, "渲染主播"))
    r = cs.fetch_xiaohongshu("https://xhslink.com/m/ok")
    assert r["status"] == "live"
    assert r["nickname"] == "渲染主播"


def test_main_xhs_error_inherits_prev_live(tmp_path, monkeypatch):
    """xhs 检测受挫（短链失效→error）应沿用上次 live 状态，不误标下播、不漏推恢复开播。"""
    rooms = [{"platform": "xhs", "id": "https://xhslink.com/m/dead", "name": "小红书测试号"}]
    for f, content in (
        ("rooms.json", json.dumps(rooms)),
        ("state.json", json.dumps({"xhs_https://xhslink.com/m/dead": "live"})),
        ("status.json", json.dumps({"updated": "", "rooms": [
            {"platform": "xhs", "id": "https://xhslink.com/m/dead", "name": "小红书测试号",
             "status": "live", "title": "旧标题", "online": 50, "area": ""}]})),
    ):
        (tmp_path / f).write_text(content, encoding="utf-8")
    monkeypatch.setattr(cs, "ROOMS_FILE", str(tmp_path / "rooms.json"))
    monkeypatch.setattr(cs, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(cs, "STATUS_FILE", str(tmp_path / "status.json"))
    monkeypatch.setattr(cs, "TRACKING_FILE", str(tmp_path / "tracking.json"))
    monkeypatch.setattr(cs, "HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setattr(cs, "_resolve_xhs_shortlink", lambda t: (t, False))
    calls = []
    monkeypatch.setattr(cs, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    monkeypatch.setenv("BLIVE_CONFIG", "{}")

    cs.main()

    st = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    # 沿用上次 live，不误标 error/offline
    assert st.get("xhs_https://xhslink.com/m/dead") == "live"
    # 检测受挫不推送
    assert calls == []

