"""阶段三 T05：小红书适配器（仅新作，直播 NotSupported）。"""

import pytest

from backend.adapters import AdapterGated
from backend.adapters.xhs import XhsAdapter


def test_xhs_live_not_supported():
    a = XhsAdapter()
    assert a.platform == "xhs"
    assert a.supports_live is False
    assert a.supports_posts is True
    assert a.needs_context is True
    # 编排层按 supports_live 跳过；此处显式抛 NotImplementedError 防误用
    with pytest.raises(NotImplementedError):
        a.fetch_room_status("x")


def test_xhs_new_posts_with_mock(monkeypatch):
    def fake_notes(self, rid):
        return [
            {
                "id": "n1",
                "title": "标题",
                "desc": "描述",
                "url": "http://x/n1",
                "cover": {"url": ["http://c1"]},
                "time": 123,
                "type": "笔记",
            }
        ]

    monkeypatch.setattr(XhsAdapter, "_fetch_notes", fake_notes)
    posts = XhsAdapter(credentials={"cookie": "c"}).fetch_new_posts("rid", baseline={})
    assert len(posts) == 1
    p = posts[0]
    assert p.post_id == "n1"
    assert p.title == "标题"
    assert p.cover == "http://c1"
    assert p.extra.get("conf") == "api"
    assert p.extra.get("type") == "笔记"
    assert p.extra.get("dedup_key") == "post:xhs:n1"


def test_xhs_new_posts_baseline_filter(monkeypatch):
    def fake_notes(self, rid):
        return [{"id": "n1", "url": "u", "cover": {"url": ["c"]}, "time": 1, "type": "笔记"}]

    monkeypatch.setattr(XhsAdapter, "_fetch_notes", fake_notes)
    posts = XhsAdapter().fetch_new_posts("rid", baseline={"latest_post_id": "n1"})
    assert posts == []


def test_xhs_new_posts_gated_when_no_creds():
    # _fetch_notes 结构占位直接抛 AdapterGated（待接入签名 API）
    with pytest.raises(AdapterGated):
        XhsAdapter().fetch_new_posts("rid", baseline={})
