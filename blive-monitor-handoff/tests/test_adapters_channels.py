"""阶段三 T05：微信视频号适配器（open_platform / playwright 双模式，结构 + 优雅降级）。"""

import pytest

from backend.adapters import AdapterGated, AdapterSkip
from backend.adapters.channels import ChannelsAdapter


def test_channels_capability_flags():
    a = ChannelsAdapter()
    assert a.platform == "channels"
    assert a.supports_live is True
    assert a.supports_posts is True
    assert a.needs_context is True
    assert a.poll_interval == 600


def test_channels_open_platform_no_creds_gated():
    a = ChannelsAdapter()  # 默认 mode=open_platform，无凭证
    with pytest.raises(AdapterGated):
        a.fetch_room_status("x")


def test_channels_open_platform_with_creds_still_pending():
    # 即便有凭证，真实开放平台接口待接入 -> 仍 AdapterGated（结构占位）
    a = ChannelsAdapter(credentials={"app_id": "id", "access_token": "tk"})
    with pytest.raises(AdapterGated):
        a.fetch_room_status("x")


def test_channels_playwright_mode_requires_context():
    a = ChannelsAdapter(credentials={"mode": "playwright"})
    with pytest.raises(AdapterSkip):
        a.fetch_room_status("x")


def test_channels_new_posts_same_semantics():
    a = ChannelsAdapter()
    with pytest.raises(AdapterGated):
        a.fetch_new_posts("x", baseline={})
    pw = ChannelsAdapter(credentials={"mode": "playwright"})
    with pytest.raises(AdapterSkip):
        pw.fetch_new_posts("x", baseline={})


def test_channels_apply_credentials():
    class FakeCtx:
        def __init__(self):
            self.cookies = []

        def add_cookies(self, items):
            self.cookies.extend(items)

    a = ChannelsAdapter(credentials={"cookie": "sess=abc"})
    ctx = FakeCtx()
    a.apply_credentials(ctx)
    assert ctx.cookies and ctx.cookies[0]["value"] == "sess=abc"
