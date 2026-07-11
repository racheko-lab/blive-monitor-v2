"""阶段三 T05：快手适配器（直播 + 新作，优雅降级）。"""

import urllib.error

import pytest

from backend.adapters import AdapterGated
from backend.adapters.kuaishou import KuaishouAdapter


def test_kuaishou_capability_flags():
    a = KuaishouAdapter()
    assert a.platform == "kuaishou"
    assert a.supports_live is True
    assert a.supports_posts is True
    assert a.needs_context is False
    assert a.poll_interval == 300


def test_kuaishou_live_api_success(monkeypatch):
    payload = (
        '{"data":{"living":true,"caption":"测试标题",'
        '"liveStreamInfo":{"watcherCount":99,"coverUrl":"http://c.jpg"}}}'
    ).encode()

    def fake_get(self, url, headers=None, timeout=10):
        return payload

    monkeypatch.setattr(KuaishouAdapter, "_http_get", fake_get)
    m = KuaishouAdapter().fetch_room_status("123")
    assert m.live_status is True
    assert m.title == "测试标题"
    assert m.online == 99
    assert m.cover == "http://c.jpg"
    assert m.extra.get("source") == "live_api"


def test_kuaishou_live_degrade_on_failure(monkeypatch):
    def fake_raise(self, *args, **kwargs):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(KuaishouAdapter, "_http_get", fake_raise)
    m = KuaishouAdapter().fetch_room_status("123")
    # 主路径 + SSR 降级均失败 -> 优雅降级为 offline，不抛异常
    assert m.live_status is False
    assert m.extra.get("degraded") is True


def test_kuaishou_room_from_html_ssr():
    html = (
        'var x=1;window.__INITIAL_STATE__={"liveroom":'
        '{"living":true,"caption":"SSR标题","watcherCount":42,"coverUrl":"http://s.jpg"}};'
        "</script>"
    )
    m = KuaishouAdapter._room_from_html("123", html)
    assert m.live_status is True
    assert m.title == "SSR标题"
    assert m.online == 42
    assert m.extra.get("source") == "ssr"


def test_kuaishou_new_posts_success(monkeypatch):
    def fake_photos(self, rid):
        return [
            {
                "photoId": "p1",
                "caption": "c1",
                "coverUrl": "http://c",
                "url": "http://u",
                "timestamp": 1000,
                "is_image": False,
            }
        ]

    monkeypatch.setattr(KuaishouAdapter, "_fetch_graphql_photos", fake_photos)
    posts = KuaishouAdapter().fetch_new_posts("rid", baseline={})
    assert len(posts) == 1
    p = posts[0]
    assert p.post_id == "p1"
    assert p.extra.get("conf") == "api"
    assert p.extra.get("type") == "视频"
    assert p.extra.get("dedup_key") == "post:kuaishou:p1"


def test_kuaishou_new_posts_baseline_filter(monkeypatch):
    def fake_photos(self, rid):
        return [{"photoId": "p1", "caption": "c1", "timestamp": 1000, "is_image": False}]

    monkeypatch.setattr(KuaishouAdapter, "_fetch_graphql_photos", fake_photos)
    # 基线已含 p1 -> 视为无新作
    posts = KuaishouAdapter().fetch_new_posts("rid", baseline={"latest_post_id": "p1"})
    assert posts == []


def test_kuaishou_new_posts_gated_on_failure(monkeypatch):
    def fake_photos(self, rid):
        raise RuntimeError("风控")

    monkeypatch.setattr(KuaishouAdapter, "_fetch_graphql_photos", fake_photos)
    with pytest.raises(AdapterGated):
        KuaishouAdapter().fetch_new_posts("rid", baseline={})
