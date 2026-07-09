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

