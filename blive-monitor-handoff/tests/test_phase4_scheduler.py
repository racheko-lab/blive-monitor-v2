"""阶段四调度器测试（run_live 一次，无网络）。

monkeypatch：
  - check_status.fetch_bilibili_batch -> 返回伪造的开播数据（避免真实网络抓取）
  - push_utils.dispatch_push / check_status.dispatch_event -> 返回伪造成功结果（避免真实推送）
调用 DetectionService().run_live() 一次，断言：不抛异常、状态成功落库（rooms.live_status='live'）、
事件历史写入。用临时 SQLite 隔离。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.db as dbmod
from backend.core.persistence import Persistence
from backend.jobs.detection_service import DetectionService


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


def test_run_live_writes_state(sched_env, monkeypatch):
    import check_status
    import push_utils
    from push_utils import SendResult

    # 预置一个直播监控房间（kind='live'）。
    Persistence().upsert_room(
        {"platform": "bilibili", "external_id": "22230707", "kind": "live", "name": "测试"}
    )

    # 伪造 B 站批量抓取 -> 返回「开播(live_status=1)」。
    def fake_fetch_bilibili_batch(ids):
        return {
            str(i): {
                "live_status": 1,
                "title": "测试标题",
                "online": 10,
                "parent_area_name": "游戏",
                "area_name": "手游",
            }
            for i in ids
        }

    monkeypatch.setattr(check_status, "fetch_bilibili_batch", fake_fetch_bilibili_batch)

    # 伪造推送：返回成功，避免真实网络调用。
    fake_ok = SendResult(ok=True, attempts=1, last_error="", status_code=200)
    monkeypatch.setattr(push_utils, "dispatch_push", lambda *a, **k: fake_ok)
    monkeypatch.setattr(check_status, "dispatch_event", lambda *a, **k: fake_ok)

    # 运行一轮直播检测（编排 + 落库）。
    ds = DetectionService()
    ds.run_live()  # 不应抛异常

    # 状态成功写入 rooms 表。
    room = Persistence().get_room_by_key("bilibili", "22230707", "live")
    assert room is not None
    assert room.live_status == "live"
    assert room.current_title == "测试标题"
    assert room.online == 10

    # 事件历史应有写入（开播事件）。
    assert Persistence().count_events() >= 1


def test_run_live_no_rooms_is_noop(sched_env, monkeypatch):
    """无监控房间时 run_live 不应抛异常（幂等空跑）。"""
    import check_status
    import push_utils
    from push_utils import SendResult

    monkeypatch.setattr(check_status, "fetch_bilibili_batch", lambda ids: {})
    fake_ok = SendResult(ok=True, attempts=1, last_error="", status_code=200)
    monkeypatch.setattr(push_utils, "dispatch_push", lambda *a, **k: fake_ok)
    monkeypatch.setattr(check_status, "dispatch_event", lambda *a, **k: fake_ok)

    ds = DetectionService()
    ds.run_live()  # 空跑，不抛异常
    assert Persistence().count_rooms() == 0
