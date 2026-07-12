"""阶段三 T05：既有 bilibili / douyin 适配器化后行为对齐（复用纯函数，零重写）。"""

import pytest

import check_new_posts
import check_status
from backend.adapters.bilibili import BilibiliAdapter
from backend.adapters.douyin import DouyinAdapter


def test_bilibili_batch_maps_live_and_replay(monkeypatch):
    def fake(ids):
        return {
            str(i): {
                "live_status": 1,
                "title": "T",
                "online": 3,
                "parent_area_name": "G",
                "area_name": "A",
            }
            for i in ids
        }

    monkeypatch.setattr(check_status, "fetch_bilibili_batch", fake)
    a = BilibiliAdapter()
    out = a.fetch_room_status_batch(["1", "2"])
    assert out["1"].live_status is True
    assert out["1"].title == "T"
    assert out["1"].online == 3
    assert out["1"].area == "G·A"
    assert out["1"].extra["status_str"] == "live"

    # replay 状态映射
    def fake2(ids):
        return {"1": {"live_status": 2, "title": "R"}}

    monkeypatch.setattr(check_status, "fetch_bilibili_batch", fake2)
    out2 = a.fetch_room_status_batch(["1"])
    assert out2["1"].live_status is False
    assert out2["1"].extra["status_str"] == "replay"


def test_douyin_fetch_new_posts_returns_new(monkeypatch):
    monkeypatch.setattr(check_new_posts, "resolve_sec_uid", lambda ctx, rid: "MS4wX")
    monkeypatch.setattr(
        check_new_posts,
        "get_latest_aweme",
        lambda ctx, sec: {
            "aweme_id": "1",
            "desc": "d",
            "video_url": "http://v",
            "is_note": False,
            "nickname": "N",
            "create_time": 100,
            "_conf": "api",
            "actual_unique_id": "h",
            "cover": "http://cv",
        },
    )
    monkeypatch.setattr(check_new_posts, "should_notify_new_post", lambda *a: True)
    monkeypatch.setattr(check_new_posts, "should_update_baseline", lambda *a: True)
    monkeypatch.setattr(check_new_posts, "looks_like_handle", lambda rid: False)

    a = DouyinAdapter()
    baseline: dict = {}
    posts = a.fetch_new_posts("h", baseline=baseline, context=object())
    assert len(posts) == 1
    p = posts[0]
    assert p.post_id == "1"
    assert p.author == "N"
    assert p.extra["conf"] == "api"
    assert p.extra["type"] == "视频"
    assert p.extra["dedup_key"] == "post:MS4wX:1"
    # 基线被适配器原地更新（sec_uid + latest_aweme_id）
    assert baseline["latest_aweme_id"] == "1"
    assert baseline["sec_uid"] == "MS4wX"


def test_douyin_fetch_new_posts_no_sec_uid_skip(monkeypatch):
    monkeypatch.setattr(check_new_posts, "resolve_sec_uid", lambda ctx, rid: None)
    a = DouyinAdapter()
    from backend.adapters import AdapterSkip

    with pytest.raises(AdapterSkip):
        a.fetch_new_posts("h", baseline={}, context=object())
