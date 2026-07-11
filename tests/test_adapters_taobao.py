"""阶段三 T05：淘宝直播适配器（仅直播，新作 NotSupported）。"""

import pytest

from backend.adapters import AdapterGated  # noqa: F401
from backend.adapters.taobao_live import TaobaoLiveAdapter


def test_taobao_capability_flags():
    a = TaobaoLiveAdapter()
    assert a.platform == "taobao_live"
    assert a.supports_live is True
    assert a.supports_posts is False
    assert a.needs_context is False
    assert a.poll_interval == 300


def test_taobao_new_posts_not_supported():
    a = TaobaoLiveAdapter()
    with pytest.raises(NotImplementedError):
        a.fetch_new_posts("x", baseline={})


def test_taobao_live_ssr_parse(monkeypatch):
    html = (
        'prefix window.__INITIAL_STATE__ = {"liveRoom":'
        '{"liveStatus":1,"title":"T","onlineCount":7,"coverUrl":"http://c"}};'
        "suffix"
    )

    def fake_get(self, url, timeout=10):
        return html.encode()

    monkeypatch.setattr(TaobaoLiveAdapter, "_http_get", fake_get)
    m = TaobaoLiveAdapter().fetch_room_status("5")
    assert m.live_status is True
    assert m.title == "T"
    assert m.online == 7
    assert m.cover == "http://c"
    assert m.extra.get("live_status_raw") == 1


def test_taobao_live_degrade_on_failure(monkeypatch):
    def fake_raise(self, *args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(TaobaoLiveAdapter, "_http_get", fake_raise)
    m = TaobaoLiveAdapter().fetch_room_status("5")
    assert m.live_status is False
    assert m.extra.get("degraded") is True
