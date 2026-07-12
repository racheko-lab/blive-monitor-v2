"""阶段二 2b · A2 多通道路由：前端 schema + UI + Python 参考实现。

grep 契约：
  - monitor.html 必须含 channelRoutes（路由容器 id）/ renderChannelRoutes /
    addChannelRoute / buildPushConfigV2 / resolveChannel（函数名）。
  - BLIVE_CONFIG 新结构：channels[] / routes[]（前端落库，CI 多通道消费留后续）。

Python 参考实现镜像 common.resolve_channel（最具体优先 + default 兜底），
并用「平台/标签/事件」多维匹配用例验证（含 default 兜底、legacy 单通道退化）。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")

import common


# ---------------------------------------------------------------------------
# grep 契约
# ---------------------------------------------------------------------------
def test_html_channel_routes_contract():
    src = open(HTML, encoding="utf-8").read()
    for token in [
        "channelRoutes",
        "renderChannelRoutes",
        "addChannelRoute",
        "buildPushConfigV2",
        "resolveChannel",
    ]:
        assert token in src, f"monitor.html 缺少 A2 契约标记: {token}"


def test_html_blive_config_new_schema():
    """前端落库结构含 channels / routes / templates（与 design §3.3 一致）。"""
    src = open(HTML, encoding="utf-8").read()
    # buildPushConfig / buildPushConfigV2 写入 channels / routes / templates
    assert "full.channels" in src, "BLIVE_CONFIG.channels 未落库"
    assert "full.routes" in src, "BLIVE_CONFIG.routes 未落库"
    assert "full.templates" in src, "BLIVE_CONFIG.templates 未落库"


def test_load_push_cfg_compat_new_structure():
    """load_push_cfg 兼容读旧单通道 push 与新 channels/routes（不破现有推送）。"""
    # 旧单通道
    assert common is not None  # 占位，真正断言在 push_utils 测试中
    from push_utils import load_push_cfg
    legacy = load_push_cfg('{"push": {"type": "bark", "url": "https://api.day.app/k"}}')
    assert legacy.get("type") == "bark", legacy
    # 新结构（仍保留 legacy push，相容）
    new = load_push_cfg(
        '{"push": {"type": "bark", "url": "u"}, '
        '"channels": [{"id": "c1", "type": "bark", "fields": {"url": "u"}}], '
        '"routes": [{"match": {"event": "live_on"}, "channelId": "c1"}]}'
    )
    assert new.get("type") == "bark", new


# ---------------------------------------------------------------------------
# Python 参考实现（镜像 common.resolve_channel）
# ---------------------------------------------------------------------------
def _cfg(channels, routes, push=None):
    return {"channels": channels, "routes": routes, "push": push or {}}


def test_resolve_channel_most_specific_first():
    cfg = _cfg(
        [
            {"id": "c_bark", "type": "bark"},
            {"id": "c_wecom", "type": "wecom"},
        ],
        [
            {"match": {"event": "live_on", "platform": "bilibili", "tag": "game"}, "channelId": "c_bark"},
            {"match": {"platform": "bilibili"}, "channelId": "c_wecom"},
        ],
    )
    # 三维命中最具体规则 → c_bark
    assert common.resolve_channel(
        cfg, {"platform": "bilibili", "tag": "game", "event": "live_on"}
    )["id"] == "c_bark"
    # 仅平台命中 → c_wecom
    assert common.resolve_channel(
        cfg, {"platform": "bilibili", "event": "new_post"}
    )["id"] == "c_wecom"


def test_resolve_channel_single_dim_priority():
    cfg = _cfg(
        [{"id": "c1", "type": "bark"}, {"id": "c2", "type": "wecom"}],
        [
            {"match": {"tag": "game"}, "channelId": "c1"},
            {"match": {"event": "live_on"}, "channelId": "c2"},
        ],
    )
    # 仅 tag 命中
    assert common.resolve_channel(cfg, {"tag": "game", "event": "new_post"})["id"] == "c1"
    # 仅 event 命中
    assert common.resolve_channel(cfg, {"tag": "x", "event": "live_on"})["id"] == "c2"


def test_resolve_channel_default_fallback():
    cfg = _cfg(
        [{"id": "c1", "type": "bark"}, {"id": "c_default", "type": "wecom"}],
        [
            {"match": {"event": "live_on", "platform": "bilibili"}, "channelId": "c1"},
            {"match": {}, "channelId": "c_default"},  # default 兜底
        ],
    )
    # 无具体规则命中（douyin + 非 live_on）→ default
    assert common.resolve_channel(
        cfg, {"platform": "douyin", "event": "new_post"}
    )["id"] == "c_default"


def test_resolve_channel_legacy_push_fallback():
    """无 routes 时退化到 legacy 单通道 push。"""
    cfg = {"channels": [{"id": "c1", "type": "bark"}], "routes": [], "push": {"type": "serverchan", "sendkey": "k"}}
    res = common.resolve_channel(cfg, {"platform": "douyin", "event": "new_post"})
    assert res.get("type") == "serverchan", res
