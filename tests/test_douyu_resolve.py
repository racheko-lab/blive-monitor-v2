"""tools/douyu_resolve.py 单测（全打桩，不依赖外网）。

背景：斗鱼 App 分享链接的路径数字**不是**房间号。实测样本
`https://m.douyu.com/15000?dyshid=...` 的页面里：
    "roomId":"15000"     <- 照抄 URL，不可信
    "rid":796449         <- 真实房间号
若信了 URL 路径，会监控到另一个已注销的房间。
"""

import pytest

from tools.douyu_resolve import (
    RE_RID,
    extract_rid,
    normalize_input,
    resolve,
)

# 2026-10-03 实抓样本的关键片段（完整页面 135KB，此处只留解析所需字段）
SHARE_HTML = (
    '<meta property="og:title" content="宁波小骚骚0oO-斗鱼直播"/>'
    '<script>window.__INIT={"roomId":"15000","rid":796449,'
    '"nickname":"宁波小骚骚0oO","roomName":"感谢bbbb的总榜一！！"}</script>'
)
NORMAL_HTML = (
    '<script>window.__INIT={"roomId":"796449","rid":796449,'
    '"nickname":"宁波小骚骚0oO","roomName":"感谢bbbb的总榜一！！"}</script>'
)


def test_extract_rid_prefers_rid_over_room_id():
    """必须取 `"rid"`，不能取 `"roomId"`（后者只是照抄 URL）。"""
    assert extract_rid(SHARE_HTML) == "796449"
    # roomId 是 15000，但 rid 才是真身
    assert '"roomId":"15000"' in SHARE_HTML
    assert extract_rid(SHARE_HTML) != "15000"


def test_extract_rid_missing():
    assert extract_rid("<html>no data</html>") is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("796449", "https://m.douyu.com/796449"),
        ("https://m.douyu.com/15000", "https://m.douyu.com/15000"),
        ("http://www.douyu.com/796449", "http://www.douyu.com/796449"),
        ("//m.douyu.com/796449", "https://m.douyu.com/796449"),
        ("m.douyu.com/796449", "https://m.douyu.com/796449"),
    ],
)
def test_normalize_input(raw, expected):
    assert normalize_input(raw) == expected


def test_resolve_share_link_mismatch(monkeypatch):
    """分享链接：路径 15000，真实房间 796449，必须以后者为准并标注来源。"""
    monkeypatch.setattr("tools.douyu_resolve.http_get", lambda url, timeout=15: SHARE_HTML)
    r = resolve("https://m.douyu.com/15000?dyshid=abc&dyshci=124")
    assert r["path_id"] == "15000"
    assert r["room_id"] == "796449"
    assert r["source"] == "ssr_rid"
    assert r["nickname"] == "宁波小骚骚0oO"
    assert r["title"] == "感谢bbbb的总榜一！！"
    assert r["path_id"] != r["room_id"]  # 解析器的价值就在于识别这种不一致


def test_resolve_plain_room_id(monkeypatch):
    """裸房间号：路径与真实房间一致，不触发「不可信」标注。"""
    monkeypatch.setattr("tools.douyu_resolve.http_get", lambda url, timeout=15: NORMAL_HTML)
    r = resolve("796449")
    assert r["path_id"] == r["room_id"] == "796449"
    assert r["source"] == "ssr_rid"
    assert not r["error"]


def test_resolve_fallback_to_url_path_is_flagged(monkeypatch):
    """页面抓不到 rid 时退回 URL 路径，但必须标 source=url_path 并给出告警。"""
    monkeypatch.setattr(
        "tools.douyu_resolve.http_get",
        lambda url, timeout=15: (_ for _ in ()).throw(OSError("网络不可达")),
    )
    r = resolve("15000")
    assert r["room_id"] == "15000"      # 兜底仍有值，不静默失败
    assert r["source"] == "url_path"    # 但明确标注不可信
    assert "页面抓取失败" in r["error"]
