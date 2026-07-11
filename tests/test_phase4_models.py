"""阶段四后端模型层测试（核心路径）。

用临时 SQLite 库（tmp_path）隔离，验证：
  - rooms CRUD（含 kind live/post 维度 + UNIQUE(platform, external_id, kind) 不丢数据）
  - events_history 写入与查询
  - notify_dedup 标记与冷却
  - set_room_status 状态列落库

所有写操作经由 ``db.WRITER_LOCK`` / SessionLocal，本测试通过 monkeypatch engine 指向临时库。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.db as dbmod
from backend.core.dedup import DedupService
from backend.core.persistence import Persistence


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """将 backend 的 engine / SessionLocal 指向临时 SQLite 文件并建表。"""
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
    import backend.models  # noqa: F401  (注册全部 ORM 到 Base.metadata)

    dbmod.Base.metadata.create_all(eng)
    yield eng


def test_rooms_crud_kind_dimension(tmp_db):
    pers = Persistence()
    # 同一抖音号同时是直播监控目标与新作监控目标 -> 两行都需保留（不丢数据）。
    pers.upsert_room(
        {"platform": "douyin", "external_id": "601914453", "kind": "live", "name": "直播A"}
    )
    pers.upsert_room(
        {"platform": "douyin", "external_id": "601914453", "kind": "post", "name": "作品A"}
    )
    assert pers.count_rooms() == 2

    live = pers.get_room_by_key("douyin", "601914453", "live")
    post = pers.get_room_by_key("douyin", "601914453", "post")
    assert live is not None and post is not None
    assert live.kind == "live" and post.kind == "post"

    # 幂等 upsert 同一行 -> 不新增（UNIQUE 约束生效）。
    pers.upsert_room(
        {"platform": "douyin", "external_id": "601914453", "kind": "live", "name": "直播A2"}
    )
    assert pers.count_rooms() == 2
    assert pers.get_room_by_key("douyin", "601914453", "live").name == "直播A2"

    # 列表过滤按 kind。
    assert pers.count_rooms(kind="live") == 1
    assert pers.count_rooms(kind="post") == 1


def test_rooms_update_and_delete(tmp_db):
    pers = Persistence()
    room = pers.upsert_room(
        {"platform": "bilibili", "external_id": "22230707", "kind": "live", "name": "x", "tags": ["a"]}
    )
    rid = room.id

    updated = pers.update_room(rid, {"name": "y", "enabled": False, "tags": ["b", "c"]})
    assert updated is not None
    assert updated.name == "y"
    assert updated.enabled is False
    assert updated.tags == ["b", "c"]

    assert pers.delete_room(rid) is True
    assert pers.get_room(rid) is None
    # 删除不存在的返回 False。
    assert pers.delete_room(rid) is False


def test_set_room_status_writes_columns(tmp_db):
    pers = Persistence()
    pers.upsert_room({"platform": "bilibili", "external_id": "22230707", "kind": "live", "name": "x"})
    room = pers.set_room_status(
        platform="bilibili",
        external_id="22230707",
        kind="live",
        name="x",
        status_item={
            "status": "live",
            "title": "标题T",
            "online": 5,
            "area": "游戏",
            "time": "2024-01-01 00:00:00",
            "last_live": "2024-01-01 00:00:00",
        },
        meta_update={"sec_uid": "u1", "live_start": "2024-01-01 00:00:00"},
    )
    assert room.live_status == "live"
    assert room.current_title == "标题T"
    assert room.online == 5
    assert room.area == "游戏"
    assert room.meta.get("sec_uid") == "u1"
    assert room.meta.get("live_start") == "2024-01-01 00:00:00"
    assert room.last_live_at == "2024-01-01 00:00:00"


def test_events_history_write_and_query(tmp_db):
    pers = Persistence()
    pers.append_event(
        {
            "time": "2024-01-01 00:00:00",
            "rid": "bilibili_1",
            "account": "bilibili_1",
            "name": "n1",
            "platform": "bilibili",
            "type": "live_on",
            "status": "live",
            "title": "t1",
        }
    )
    pers.append_event(
        {
            "time": "2024-01-02 00:00:00",
            "rid": "bilibili_2",
            "type": "new_post",
            "status": "new_post",
        }
    )
    assert pers.count_events() == 2

    bili = pers.list_events(platform="bilibili")
    assert len(bili) == 1
    assert bili[0].raw_rid == "bilibili_1"
    assert bili[0].event_type == "live_on"

    # 按 room_id 过滤（无关联 room 时为 None）。
    assert pers.count_events(room_id=None) == 2


def test_notify_dedup_mark_and_cooldown(tmp_db):
    d = DedupService()
    key = "live:douyin_601914453"
    # 未记录 -> 可推送。
    assert d.should_notify(key) is True
    # 记录后（默认 2h 冷却）-> 冷却期内不可推送。
    d.record(key)
    assert d.last_sent_at(key) > 0
    assert d.should_notify(key) is False
    # 超过冷却 -> 可再次推送。
    assert d.should_notify(key, cooldown=0.0) is True


def test_posts_upsert(tmp_db):
    pers = Persistence()
    p1 = pers.upsert_post(
        {"platform": "douyin", "post_id": "123", "author": "nick", "cover": "http://c"}
    )
    assert p1.id is not None
    # 幂等：同 (platform, post_id) 不新增。
    pers.upsert_post({"platform": "douyin", "post_id": "123", "author": "nick2"})
    assert pers.count_posts() == 1
    assert pers.get_post(p1.id).author == "nick2"
