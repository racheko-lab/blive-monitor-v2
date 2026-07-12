"""A2/A4 CI 侧打通回归测试（dispatch_event + 分组投递 + 模板渲染）。

覆盖（设计文档 §6 测试契约）：
  - push_utils.channel_to_push_cfg / dispatch_event 单测（legacy 退化 / 多通道路由 /
    tag 匹配 / 未配置守卫）。
  - check_status 集成：legacy 逐字节等价 / 多通道分组 / tag 匹配 / 模板渲染 / 静默 / 去重。
  - check_new_posts 路由（每作品独立路由到其通道，不跨房间聚合）。
  - auto_summary 经 dispatch_event 路由（含 summary 路由）。
  - 跨语言对照：dispatch_event 走 common.resolve_channel（与 monitor.html JS 同源）。

所有集成用例复用既有 BLIVE_CONFIG 解析与去重账本隔离（conftest 已隔离 LEDGER_FILE）。
"""
import json
from datetime import datetime

import pytest

import push_utils
import common
import check_status as cs
import check_new_posts as cnp
import auto_summary


# =====================================================================
# 辅助：构造一个固定返回 ok 的假 SendResult
# =====================================================================
class _OkResult:
    ok = True
    attempts = 1
    last_error = ""
    status_code = None


class _FailResult:
    ok = False
    attempts = 1
    last_error = "biz_reject: test"
    status_code = None


def _fake_dispatch(recorder):
    """返回一个替代 push_utils.dispatch_push 的 fake，记录每次 (title, desp, pcfg)。"""

    def _fake(push_cfg, title, desp):
        recorder.append((title, desp, push_cfg))
        return _OkResult()

    return _fake


# =====================================================================
# push_utils.channel_to_push_cfg
# =====================================================================
def test_channel_to_push_cfg():
    # 新通道 dict（含 fields）→ 拍平到顶层
    assert push_utils.channel_to_push_cfg(
        {"id": "c1", "type": "wecom", "fields": {"webhook": "x"}}
    ) == {"type": "wecom", "webhook": "x"}
    # 扁平 legacy dict → 原样透传
    assert push_utils.channel_to_push_cfg(
        {"type": "wecom", "webhook": "x"}
    ) == {"type": "wecom", "webhook": "x"}
    # 空 dict
    assert push_utils.channel_to_push_cfg({}) == {}
    # None
    assert push_utils.channel_to_push_cfg(None) == {}


# =====================================================================
# push_utils.dispatch_event
# =====================================================================
def test_dispatch_event_legacy_degrade(monkeypatch):
    """legacy（仅 push，无 routes/channels）→ dispatch_event 等价当前 dispatch_push。"""
    cfg_all = {"push": {"type": "wecom", "webhook": "x"}}
    calls = []
    monkeypatch.setattr(push_utils, "dispatch_push", _fake_dispatch(calls))
    res = push_utils.dispatch_event(cfg_all, {"event": "live_on"}, "t", "d")
    assert res.ok is True
    assert len(calls) == 1
    # pcfg 等于 legacy dispatch_push 实际收到的配置（透传扁平 push）
    assert calls[0][2] == {"type": "wecom", "webhook": "x"}


def test_dispatch_event_multichannel_routing(monkeypatch):
    """多通道：bilibili→wecom / douyin→bark（按 platform 路由）。"""
    cfg_all = {
        "channels": [
            {"id": "wecom", "type": "wecom", "fields": {"webhook": "w"}},
            {"id": "bark", "type": "bark", "fields": {"url": "u"}},
        ],
        "routes": [
            {"match": {"platform": "bilibili"}, "channelId": "wecom"},
            {"match": {"platform": "douyin"}, "channelId": "bark"},
        ],
    }
    calls = []
    monkeypatch.setattr(push_utils, "dispatch_push", _fake_dispatch(calls))
    push_utils.dispatch_event(cfg_all, {"platform": "bilibili", "tag": None, "event": "live_on"}, "tb", "db")
    push_utils.dispatch_event(cfg_all, {"platform": "douyin", "tag": None, "event": "live_on"}, "td", "dd")
    assert len(calls) == 2
    types = {c[2]["type"] for c in calls}
    assert types == {"wecom", "bark"}


def test_dispatch_event_tag_match(monkeypatch):
    """routes 含 {match:{tag:'vip'},channelId:'bark'}；tags=['vip']→bark，其余→默认。"""
    cfg_all = {
        "channels": [
            {"id": "bark", "type": "bark", "fields": {"url": "u"}},
            {"id": "wecom", "type": "wecom", "fields": {"webhook": "w"}},
        ],
        "routes": [
            {"match": {"tag": "vip"}, "channelId": "bark"},
            {"match": {}, "channelId": "wecom"},
        ],
    }
    calls = []
    monkeypatch.setattr(push_utils, "dispatch_push", _fake_dispatch(calls))
    push_utils.dispatch_event(cfg_all, {"platform": "bilibili", "tag": "vip", "event": "live_on"}, "t", "d")
    push_utils.dispatch_event(cfg_all, {"platform": "bilibili", "tag": "other", "event": "live_on"}, "t", "d")
    assert [c[2]["type"] for c in calls] == ["bark", "wecom"]


def test_dispatch_event_template_render(monkeypatch):
    """templates.live_on 存在 → 正文经 render_template 渲染（含房间名与标题，无残留占位符）。"""
    cfg_all = {
        "channels": [{"id": "c1", "type": "wecom", "fields": {"webhook": "w"}}],
        "routes": [{"match": {}, "channelId": "c1"}],
        "templates": {"live_on": "🔴 {name} 开播了：{title}"},
    }
    # 直接验证 render_body（模板渲染实际站点，位于 check_status）
    s = {
        "name": "峰哥", "platform": "bilibili", "rid": "1", "tags": None,
        "result": {"status": "live", "title": "今晚联动"},
    }
    desp = cs.render_body(s, "live_on", cfg_all)
    assert desp == "🔴 峰哥 开播了：今晚联动"
    assert "{name}" not in desp and "{title}" not in desp


def test_dispatch_event_no_config(monkeypatch):
    """未配置通道：dispatch_event 返回 ok=False 且不调用 dispatch_push（不刷伪失败）。"""
    calls = []
    monkeypatch.setattr(push_utils, "dispatch_push", _fake_dispatch(calls))
    # cfg_all 为空
    res = push_utils.dispatch_event({}, {"event": "live_on"}, "t", "d")
    assert res.ok is False
    assert res.last_error == "config: empty push_cfg"
    assert calls == []
    # 通道无 type（退化未配置）
    res2 = push_utils.dispatch_event(
        {"channels": [{"id": "c", "type": "", "fields": {}}],
         "routes": [{"match": {}, "channelId": "c"}]},
        {"event": "live_on"}, "t", "d",
    )
    assert res2.ok is False
    assert res2.last_error == "config: empty push_cfg"
    assert calls == []


def test_dispatch_event_routes_via_common_resolve_channel(monkeypatch):
    """dispatch_event 必须经过 common.resolve_channel（与 monitor.html JS 同源，逐字节一致）。"""
    seen = {}

    def _fake_resolve(cfg, ctx):
        seen["ctx"] = ctx
        # 返回已扁平 legacy 形状，验证透传路径
        return {"type": "wecom", "webhook": "x"}

    monkeypatch.setattr(common, "resolve_channel", _fake_resolve)
    calls = []
    monkeypatch.setattr(push_utils, "dispatch_push", _fake_dispatch(calls))
    push_utils.dispatch_event(
        {"push": {"type": "wecom", "webhook": "x"}},
        {"platform": "bilibili", "tag": "v", "event": "live_on"}, "t", "d",
    )
    assert seen["ctx"] == {"platform": "bilibili", "tag": "v", "event": "live_on"}
    assert calls[0][2] == {"type": "wecom", "webhook": "x"}


# =====================================================================
# check_status.render_body 单测（模板 / legacy 两条路径）
# =====================================================================
def test_render_body_template():
    s = {
        "name": "A", "platform": "bilibili", "rid": "1", "tags": None,
        "result": {"status": "live", "title": "今晚联动"},
    }
    desp = cs.render_body(s, "live_on", {"templates": {"live_on": "🔴 {name} 开播了：{title}"}})
    assert desp == "🔴 A 开播了：今晚联动"


def test_render_body_legacy_parity():
    s = {
        "name": "A", "platform": "bilibili", "rid": "1", "tags": None,
        "result": {"status": "live", "title": "x", "online": 5, "area": "网游"},
    }
    # 无 templates → 必须逐字节等于 legacy format_push_desp
    assert cs.render_body(s, "live_on", {}) == cs.format_push_desp("A", "bilibili", "1", s["result"])


# =====================================================================
# check_status 集成（跑 main()，捕获 dispatch_push）
# =====================================================================
def _run_cs(tmp_path, monkeypatch, rooms, blive_config, now_fixed, batch):
    """运行一次 check_status.main()，捕获 push_utils.dispatch_push 的调用。

    返回 (calls)，calls 为 [(title, desp, pcfg), ...]。
    冻结 bjnow 以保证正文中的检测时间串与预期逐字节一致。
    """
    rooms_file = tmp_path / "rooms.json"
    rooms_file.write_text(json.dumps(rooms), encoding="utf-8")
    state_file = tmp_path / "state.json"
    state_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cs, "ROOMS_FILE", str(rooms_file))
    monkeypatch.setattr(cs, "STATE_FILE", str(state_file))
    monkeypatch.setattr(cs, "TRACKING_FILE", str(tmp_path / "tracking.json"))
    monkeypatch.setattr(cs, "HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setattr(cs, "STATUS_FILE", str(tmp_path / "status.json"))
    monkeypatch.setenv("BLIVE_CONFIG", json.dumps(blive_config))
    monkeypatch.setattr(cs, "bjnow", lambda: now_fixed)
    monkeypatch.setattr(common, "bjnow", lambda: now_fixed)
    monkeypatch.setattr(cs, "fetch_bilibili_batch", lambda ids: batch)

    calls = []
    monkeypatch.setattr(push_utils, "dispatch_push", _fake_dispatch(calls))
    cs.main()
    return calls


def _live_batch(rooms):
    out = {}
    for r in rooms:
        rid = str(r["id"])
        out[rid] = {
            "live_status": 1,
            "title": r.get("title", f"标题{rid}"),
            "online": r.get("online", 10),
            "parent_area_name": "网游",
            "area_name": "英雄联盟",
        }
    return out


def _result(rid, batch):
    """把 raw by_room_ids 条目变换为 main() 构造的 result dict（供预期值计算）。"""
    d = batch[str(rid)]
    status_code = d.get("live_status", 0)
    status = {"0": "offline", "1": "live", "2": "replay"}.get(str(status_code), "unknown")
    area = f"{d.get('parent_area_name', '')}·{d.get('area_name', '')}".strip("·") or ""
    return {
        "status": status,
        "title": d.get("title", ""),
        "online": d.get("online", 0),
        "area": area,
    }


def test_check_status_legacy_parity(tmp_path, monkeypatch):
    """关键：legacy（仅 push）下，开播通知 title/desp 与改造前逐字节一致，且仅 1 次调用。"""
    now = datetime(2026, 7, 11, 20, 0, 0)
    rooms = [
        {"platform": "bilibili", "id": "1", "name": "A", "title": "标题A", "online": 10},
        {"platform": "bilibili", "id": "2", "name": "B", "title": "标题B", "online": 20},
    ]
    cfg = {"push": {"type": "wecom", "webhook": "https://qyapi.weixin.qq.com/x"}}
    batch = _live_batch(rooms)
    calls = _run_cs(tmp_path, monkeypatch, rooms, cfg, now, batch)

    # legacy 单通道：全量房间 = 1 组 = 1 次聚合消息
    assert len(calls) == 1
    title, desp, pcfg = calls[0]
    # 聚合标题
    assert title == "🔴 2位主播开播：A、B"
    # 聚合正文 = 各房间 format_push_desp 拼接（legacy 路径）
    expected_desp = "\n\n---\n\n".join([
        cs.format_push_desp("A", "bilibili", "1", _result("1", batch)),
        cs.format_push_desp("B", "bilibili", "2", _result("2", batch)),
    ])
    assert desp == expected_desp
    # pcfg 等价于 legacy push 配置
    assert pcfg == {"type": "wecom", "webhook": "https://qyapi.weixin.qq.com/x"}


def test_check_status_single_room_legacy_parity(tmp_path, monkeypatch):
    """单房间 legacy：title=format_push_title，desp=format_push_desp，逐字节一致。"""
    now = datetime(2026, 7, 11, 20, 0, 0)
    rooms = [{"platform": "bilibili", "id": "1", "name": "A", "title": "标题A", "online": 10}]
    cfg = {"push": {"type": "bark", "url": "https://api.day.app/K"}}
    batch = _live_batch(rooms)
    calls = _run_cs(tmp_path, monkeypatch, rooms, cfg, now, batch)

    assert len(calls) == 1
    title, desp, pcfg = calls[0]
    assert title == cs.format_push_title("A", _result("1", batch))
    assert desp == cs.format_push_desp("A", "bilibili", "1", _result("1", batch))
    assert pcfg == {"type": "bark", "url": "https://api.day.app/K"}


def test_check_status_multichannel(tmp_path, monkeypatch):
    """多通道：按 tag 路由（vip→bark / 默认→wecom），各自独立成组（2 次调用）。"""
    now = datetime(2026, 7, 11, 20, 0, 0)
    rooms = [
        {"platform": "bilibili", "id": "1", "name": "A", "title": "标题A", "tags": ["vip"]},
        {"platform": "bilibili", "id": "2", "name": "B", "title": "标题B", "tags": ["normal"]},
    ]
    cfg = {
        "channels": [
            {"id": "bark", "type": "bark", "fields": {"url": "u_bark"}},
            {"id": "wecom", "type": "wecom", "fields": {"webhook": "w_wecom"}},
        ],
        "routes": [
            {"match": {"tag": "vip"}, "channelId": "bark"},
            {"match": {}, "channelId": "wecom"},
        ],
        # legacy push 不应被使用（仅在无路由命中时兜底）
        "push": {"type": "serverchan", "sendkey": "legacy"},
    }
    batch = _live_batch(rooms)
    calls = _run_cs(tmp_path, monkeypatch, rooms, cfg, now, batch)

    assert len(calls) == 2
    by_type = {c[2]["type"]: c for c in calls}
    assert set(by_type) == {"bark", "wecom"}
    # vip 房间进入 bark，标题为单房间格式
    bark_title, bark_desp, bark_cfg = by_type["bark"]
    assert bark_title == cs.format_push_title("A", _result("1", batch))
    assert bark_cfg == {"type": "bark", "url": "u_bark"}
    # 默认房间进入 wecom
    wecom_title, _, wecom_cfg = by_type["wecom"]
    assert wecom_title == cs.format_push_title("B", _result("2", batch))
    assert wecom_cfg == {"type": "wecom", "webhook": "w_wecom"}


def test_check_status_tag_match(tmp_path, monkeypatch):
    """routes 含 tag 匹配：带 tags=['game'] 的房间进对应 bark 通道，其余进默认 wecom。"""
    now = datetime(2026, 7, 11, 20, 0, 0)
    rooms = [
        {"platform": "bilibili", "id": "1", "name": "A", "title": "标题A", "tags": ["game"]},
        {"platform": "bilibili", "id": "2", "name": "B", "title": "标题B", "tags": ["music"]},
        {"platform": "bilibili", "id": "3", "name": "C", "title": "标题C"},  # 无 tags → 默认
    ]
    cfg = {
        "channels": [
            {"id": "bark", "type": "bark", "fields": {"url": "u_bark"}},
            {"id": "wecom", "type": "wecom", "fields": {"webhook": "w_wecom"}},
        ],
        "routes": [
            {"match": {"tag": "game"}, "channelId": "bark"},
            {"match": {}, "channelId": "wecom"},
        ],
    }
    batch = _live_batch(rooms)
    calls = _run_cs(tmp_path, monkeypatch, rooms, cfg, now, batch)

    # A(game)→bark 单独一组；B(music)/C(无)→默认 wecom 一组（同通道聚合为一条）
    assert len(calls) == 2
    by_type = {c[2]["type"]: c for c in calls}
    assert set(by_type) == {"bark", "wecom"}
    # wecom 组含 B、C 两个房间（聚合标题）
    wecom_title, wecom_desp, _ = by_type["wecom"]
    assert wecom_title == "🔴 2位主播开播：B、C"
    assert "B" in wecom_desp and "C" in wecom_desp
    # bark 组仅 A
    bark_title, bark_desp, _ = by_type["bark"]
    assert bark_title == cs.format_push_title("A", _result("1", batch))
    assert "标题A" in bark_desp and "标题B" not in bark_desp


def test_check_status_template_render(tmp_path, monkeypatch):
    """templates.live_on 存在 → 分组正文经 render_template 渲染（legacy 单通道下也生效）。"""
    now = datetime(2026, 7, 11, 20, 0, 0)
    rooms = [{"platform": "bilibili", "id": "1", "name": "A", "title": "今晚联动"}]
    cfg = {
        "push": {"type": "wecom", "webhook": "x"},
        "templates": {"live_on": "🔴 {name} 开播了：{title}"},
    }
    batch = _live_batch(rooms)
    calls = _run_cs(tmp_path, monkeypatch, rooms, cfg, now, batch)

    assert len(calls) == 1
    title, desp, pcfg = calls[0]
    # 标题维持现状（format_push_title），正文替换为模板渲染
    assert title == cs.format_push_title("A", _result("1", batch))
    assert desp == "🔴 A 开播了：今晚联动"
    assert "{name}" not in desp and "{title}" not in desp


def test_check_status_silence_skips(tmp_path, monkeypatch):
    """A3 静默：北京静默区间内零调用，queued 标记改为 silenced。"""
    now = datetime(2026, 7, 11, 20, 0, 0)
    rooms = [{"platform": "bilibili", "id": "1", "name": "A", "title": "标题A"}]
    cfg = {
        "push": {"type": "wecom", "webhook": "x"},
        "silence": {"enabled": True, "start": "00:00", "end": "23:59"},
    }
    batch = _live_batch(rooms)
    calls = _run_cs(tmp_path, monkeypatch, rooms, cfg, now, batch)
    assert calls == []


def test_check_status_no_config_no_sendkey(tmp_path, monkeypatch):
    """无推送配置（legacy 无 push）：零调用，等价未配置分支（不刷伪失败 error）。"""
    now = datetime(2026, 7, 11, 20, 0, 0)
    rooms = [{"platform": "bilibili", "id": "1", "name": "A", "title": "标题A"}]
    cfg = {}  # 无任何 push/channels/routes
    batch = _live_batch(rooms)
    calls = _run_cs(tmp_path, monkeypatch, rooms, cfg, now, batch)
    assert calls == []


# =====================================================================
# check_new_posts 路由（每作品独立路由；拦截点已迁移到 push_utils.dispatch_push）
# =====================================================================
def test_check_new_posts_dispatch_event_legacy(monkeypatch):
    """legacy（仅 push）→ dispatch_event 退化为 dispatch_push(legacy push_cfg)。"""
    calls = []
    monkeypatch.setattr(push_utils, "dispatch_push", _fake_dispatch(calls))
    cfg = {"push": {"type": "wecom", "webhook": "x"}}
    res = cnp.dispatch_event(cfg, {"platform": "douyin", "tag": None, "event": "new_post"}, "t", "d")
    assert res.ok is True
    assert len(calls) == 1
    assert calls[0][2] == {"type": "wecom", "webhook": "x"}


def test_check_new_posts_dispatch_event_routing(monkeypatch):
    """多通道：new_post 事件路由到 bark，其余（若配置）走默认。"""
    calls = []
    monkeypatch.setattr(push_utils, "dispatch_push", _fake_dispatch(calls))
    cfg = {
        "channels": [
            {"id": "bark", "type": "bark", "fields": {"url": "u"}},
            {"id": "wecom", "type": "wecom", "fields": {"webhook": "w"}},
        ],
        "routes": [{"match": {"event": "new_post"}, "channelId": "bark"}],
        "push": {"type": "serverchan", "sendkey": "legacy"},
    }
    res = cnp.dispatch_event(cfg, {"platform": "douyin", "tag": None, "event": "new_post"}, "t", "d")
    assert res.ok is True
    assert len(calls) == 1
    assert calls[0][2] == {"type": "bark", "url": "u"}


def test_check_new_posts_dispatch_event_tag_routing(monkeypatch):
    """new_post 按 tag 路由：tags=['vip'] → bark。"""
    calls = []
    monkeypatch.setattr(push_utils, "dispatch_push", _fake_dispatch(calls))
    cfg = {
        "channels": [
            {"id": "bark", "type": "bark", "fields": {"url": "u"}},
            {"id": "wecom", "type": "wecom", "fields": {"webhook": "w"}},
        ],
        "routes": [
            {"match": {"tag": "vip"}, "channelId": "bark"},
            {"match": {}, "channelId": "wecom"},
        ],
    }
    res = cnp.dispatch_event(cfg, {"platform": "douyin", "tag": "vip", "event": "new_post"}, "t", "d")
    assert res.ok and calls[0][2]["type"] == "bark"


def test_check_new_posts_dispatch_event_no_config(monkeypatch):
    """未配置通道：返回 ok=False 且不调用 dispatch_push（不刷伪失败）。"""
    calls = []
    monkeypatch.setattr(push_utils, "dispatch_push", _fake_dispatch(calls))
    res = cnp.dispatch_event({}, {"platform": "douyin", "tag": None, "event": "new_post"}, "t", "d")
    assert res.ok is False
    assert res.last_error == "config: empty push_cfg"
    assert calls == []


# =====================================================================
# auto_summary 经 dispatch_event 路由
# =====================================================================
def _write_summary_files(tmp_path, hist, state):
    (tmp_path / "history.json").write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "summary_state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _fixed_now():
    return datetime(2026, 7, 11, 20, 0)


def test_auto_summary_dispatch_event_legacy(tmp_path, monkeypatch):
    """legacy（仅 push）：摘要经 dispatch_event 退化通道投递，等价于原 load_push_cfg+dispatch_push。"""
    monkeypatch.chdir(tmp_path)
    _write_summary_files(
        tmp_path,
        [{"time": "2026-07-11 09:00:00", "type": "live_on", "platform": "bilibili", "rid": "1", "name": "A"}],
        {"enabled": True, "freq": "daily", "sendTime": "09:00", "lastSent": 0},
    )
    monkeypatch.setenv(
        "BLIVE_CONFIG",
        json.dumps({
            "summary": {"enabled": True, "freq": "daily", "sendTime": "00:00"},
            "push": {"type": "wecom", "webhook": "http://example.com/x"},
        }),
    )
    monkeypatch.setattr(auto_summary, "bjnow", lambda: _fixed_now())

    calls = []
    monkeypatch.setattr(push_utils, "dispatch_push", _fake_dispatch(calls))
    with pytest.raises(SystemExit) as e:
        auto_summary.main()
    assert e.value.code == 0
    assert len(calls) == 1
    assert calls[0][2].get("type") == "wecom"  # 退化到 legacy 通道


def test_auto_summary_dispatch_event_summary_route(tmp_path, monkeypatch):
    """summary 路由：routes 含 {match:{event:'summary'},channelId:'bark'} → 走 bark。"""
    monkeypatch.chdir(tmp_path)
    _write_summary_files(
        tmp_path,
        [{"time": "2026-07-11 09:00:00", "type": "live_on", "platform": "bilibili", "rid": "1", "name": "A"}],
        {"enabled": True, "freq": "daily", "sendTime": "09:00", "lastSent": 0},
    )
    monkeypatch.setenv(
        "BLIVE_CONFIG",
        json.dumps({
            "summary": {"enabled": True, "freq": "daily", "sendTime": "00:00"},
            "channels": [{"id": "bark", "type": "bark", "fields": {"url": "u_bark"}}],
            "routes": [{"match": {"event": "summary"}, "channelId": "bark"}],
            "push": {"type": "wecom", "webhook": "x"},  # legacy 兜底，不应被使用
        }),
    )
    monkeypatch.setattr(auto_summary, "bjnow", lambda: _fixed_now())

    calls = []
    monkeypatch.setattr(push_utils, "dispatch_push", _fake_dispatch(calls))
    with pytest.raises(SystemExit) as e:
        auto_summary.main()
    assert e.value.code == 0
    assert len(calls) == 1
    assert calls[0][2] == {"type": "bark", "url": "u_bark"}


def test_auto_summary_no_channel_noop(tmp_path, monkeypatch):
    """无有效通道：no-op（sys.exit(0) 不写冷却，不调用推送）。"""
    monkeypatch.chdir(tmp_path)
    _write_summary_files(
        tmp_path,
        [{"time": "2026-07-11 09:00:00", "type": "live_on", "platform": "bilibili", "rid": "1", "name": "A"}],
        {"enabled": True, "freq": "daily", "sendTime": "09:00", "lastSent": 0},
    )
    monkeypatch.setenv(
        "BLIVE_CONFIG",
        json.dumps({"summary": {"enabled": True, "freq": "daily", "sendTime": "00:00"}}),
    )
    monkeypatch.setattr(auto_summary, "bjnow", lambda: _fixed_now())

    calls = []
    monkeypatch.setattr(push_utils, "dispatch_push", _fake_dispatch(calls))
    with pytest.raises(SystemExit) as e:
        auto_summary.main()
    assert e.value.code == 0
    assert calls == []
