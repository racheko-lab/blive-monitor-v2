"""阶段三 T05：端到端编排接线 —— 注入 mock AdapterRegistry，
验证 run_live_check / run_post_check 遍历注册表、归一化、落库、推送。
"""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.db as dbmod
from backend.adapters import AdapterRegistry, PlatformAdapter, PostModel, RoomModel
from backend.core.persistence import Persistence
from backend.jobs.live_check import LivePersist
from backend.jobs.post_check import PostPersist
from push_utils import SendResult


@pytest.fixture
def sched_env(tmp_path, monkeypatch):
    db_file = tmp_path / "blive.db"
    monkeypatch.setenv("BLIVE_DB_PATH", str(db_file))
    eng = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    monkeypatch.setattr(dbmod, "engine", eng)
    monkeypatch.setattr(
        dbmod, "SessionLocal", sessionmaker(bind=eng, expire_on_commit=False, future=True)
    )
    import backend.models  # noqa: F401

    dbmod.Base.metadata.create_all(eng)
    yield


class MockLiveAdapter(PlatformAdapter):
    platform = "mocklive"
    supports_live = True
    supports_posts = False

    def fetch_room_status(self, room_id):
        return RoomModel(
            platform="mocklive", room_id=room_id, title="M", live_status=True, online=5
        )

    def fetch_new_posts(self, *a, **k):
        raise NotImplementedError


class MockPostAdapter(PlatformAdapter):
    platform = "mockpost"
    supports_live = False
    supports_posts = True

    def fetch_room_status(self, room_id):
        raise NotImplementedError

    def fetch_new_posts(self, author_or_room, since=None, baseline=None, context=None):
        return [
            PostModel(
                platform="mockpost",
                post_id="p1",
                url="http://u",
                title="t",
                extra={"conf": "api", "type": "视频", "dedup_key": "post:mockpost:p1"},
            )
        ]


def _patch_routing(monkeypatch):
    import common

    # 让统一路由返回一个具体通道，确保 dispatch_event 真正被调用
    monkeypatch.setattr(
        common, "resolve_channel", lambda cfg, ctx: {"id": "test", "type": "bark"}
    )


def test_live_wiring_persists_and_pushes(sched_env, monkeypatch):
    import check_status

    Persistence().upsert_room(
        {"platform": "mocklive", "external_id": "777", "kind": "live", "name": "M"}
    )
    calls = []
    fake_ok = SendResult(ok=True, attempts=1, last_error="", status_code=200)
    monkeypatch.setattr(
        check_status, "dispatch_event", lambda *a, **k: (calls.append(a), fake_ok)[1]
    )
    _patch_routing(monkeypatch)

    reg = AdapterRegistry()
    reg.register(MockLiveAdapter())
    now = datetime(2026, 1, 1, 12, 0, 0)
    check_status.run_live_check(cfg_all={}, persist=LivePersist(), now=now, adapters=reg)

    room = Persistence().get_room_by_key("mocklive", "777", "live")
    assert room is not None
    assert room.live_status == "live"
    assert room.current_title == "M"
    assert room.online == 5
    assert len(calls) >= 1  # 开播推送已触发


def test_post_wiring_persists_and_pushes(sched_env, monkeypatch):
    import check_new_posts

    Persistence().upsert_room(
        {"platform": "mockpost", "external_id": "888", "kind": "post", "name": "P"}
    )
    calls = []
    fake_ok = SendResult(ok=True, attempts=1, last_error="", status_code=200)
    monkeypatch.setattr(
        check_new_posts, "dispatch_event", lambda *a, **k: (calls.append(a), fake_ok)[1]
    )
    _patch_routing(monkeypatch)

    reg = AdapterRegistry()
    reg.register(MockPostAdapter())
    now = datetime(2026, 1, 1, 12, 0, 0)
    check_new_posts.run_post_check(
        cfg_all={}, persist=PostPersist(), now=now, context=object(), adapters=reg
    )

    # 作品落 posts 表 + 新作推送触发
    assert Persistence().count_posts() == 1
    assert len(calls) >= 1


def test_post_wiring_skips_unsupported_platform(sched_env, monkeypatch):
    import check_new_posts

    # taobao_live 仅直播，新作应被编排层跳过（不抛异常、不推送）
    Persistence().upsert_room(
        {"platform": "taobao_live", "external_id": "999", "kind": "post", "name": "T"}
    )
    calls = []
    fake_ok = SendResult(ok=True, attempts=1, last_error="", status_code=200)
    monkeypatch.setattr(
        check_new_posts, "dispatch_event", lambda *a, **k: (calls.append(a), fake_ok)[1]
    )
    _patch_routing(monkeypatch)

    reg = AdapterRegistry()
    reg.register(
        type(
            "TaobaoLike",
            (PlatformAdapter,),
            {
                "platform": "taobao_live",
                "supports_live": True,
                "supports_posts": False,
                "fetch_room_status": lambda self, rid: RoomModel(
                    platform="taobao_live", room_id=rid
                ),
                "fetch_new_posts": lambda *a, **k: (_ for _ in ()).throw(NotImplementedError()),
            },
        )()
    )
    now = datetime(2026, 1, 1, 12, 0, 0)
    # 不应抛异常；taobao_live 不支持新作 -> 跳过，无推送
    check_new_posts.run_post_check(
        cfg_all={}, persist=PostPersist(), now=now, context=object(), adapters=reg
    )
    assert calls == []
    assert Persistence().count_posts() == 0
