"""check_status 单元测试：状态机、格式化、抖音提取、B站批量接口（mock 网络）。"""
import json

import pytest

import check_status as cs


# ==================== should_push（状态机） ====================

@pytest.mark.parametrize("prev,curr,expected", [
    (None, "live", True),
    (None, "replay", True),
    (None, "offline", False),
    ("offline", "live", True),
    ("offline", "replay", True),
    ("offline", "offline", False),
    ("live", "offline", False),
    ("live", "live", False),
    ("error", "live", False),   # error→live 不推送，避免检测抖动误报
    ("replay", "live", True),
    ("replay", "replay", False),
    ("offline", "error", False),
    ("live", "error", False),
])
def test_should_push(prev, curr, expected):
    assert cs.should_push(prev, curr) is expected


# ==================== 格式化 ====================

def test_format_push_title_live():
    assert cs.format_push_title("小明", {"status": "live"}) == "🔴 小明 开播了！"


def test_format_push_title_replay():
    assert "轮播" in cs.format_push_title("小明", {"status": "replay"})


def test_format_push_desp_bilibili():
    desp = cs.format_push_desp(
        "小明", "bilibili", "187", {"status": "live", "title": "今晚直播", "area": "网游", "online": 99}
    )
    assert "live.bilibili.com/187" in desp
    assert "今晚直播" in desp
    assert "网游" in desp
    assert "99" in desp


def test_format_push_desp_douyin():
    desp = cs.format_push_desp(
        "小红", "douyin", "831", {"status": "live", "title": "带货中"}
    )
    assert "live.douyin.com/831" in desp
    assert "带货中" in desp


# ==================== calculate_duration ====================

@pytest.mark.parametrize("start,now,expected", [
    ("2024-01-01 10:00:00", "2024-01-01 10:45:00", "45min"),
    ("2024-01-01 10:00:00", "2024-01-01 11:30:00", "1h30min"),
    ("2024-01-01 10:00:00", "2024-01-01 10:00:00", "0min"),
])
def test_calculate_duration(start, now, expected):
    from datetime import datetime
    now_dt = datetime.strptime(now, "%Y-%m-%d %H:%M:%S")
    assert cs.calculate_duration(start, now_dt) == expected


def test_calculate_duration_bad_input():
    from datetime import datetime
    assert cs.calculate_duration("not-a-date", datetime.now()) == ""


# ==================== 文件读写 ====================

def test_load_save_json_roundtrip(tmp_path):
    f = tmp_path / "x.json"
    cs.save_json_file(str(f), {"a": 1})
    assert cs.load_json_file(str(f)) == {"a": 1}


def test_load_json_missing_returns_default(tmp_path):
    assert cs.load_json_file(str(tmp_path / "nope.json"), []) == []


def test_load_json_corrupt(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{broken", encoding="utf-8")
    assert cs.load_json_file(str(f), {"d": 1}) == {"d": 1}


# ==================== B站批量接口（mock 网络） ====================

def test_fetch_bilibili_batch(monkeypatch):
    sample = {
        "code": 0,
        "data": {
            "by_room_ids": {
                "1874913653": {
                    "live_status": 1,
                    "title": "测试直播",
                    "online": 123,
                    "parent_area_name": "网游",
                    "area_name": "英雄联盟",
                }
            }
        },
    }
    monkeypatch.setattr(cs, "fetch_with_retry", lambda url, headers=None: json.dumps(sample).encode())
    data = cs.fetch_bilibili_batch(["1874913653"])
    assert data["1874913653"]["live_status"] == 1


def test_fetch_bilibili_batch_error(monkeypatch):
    monkeypatch.setattr(cs, "fetch_with_retry", lambda url, headers=None: json.dumps({"code": -412, "message": "风控"}).encode())
    with pytest.raises(Exception):
        cs.fetch_bilibili_batch(["1"])


# ==================== 抖音提取策略 ====================

def test_extract_render_data_live():
    html = (
        'prefix '
        '\\"id_str\\":\\"123\\",'
        '\\"status\\":2,'
        '\\"status_str\\":\\"2\\",'
        '\\"title\\":\\"我的直播间\\"'
        ',\\"user_count_str\\":\\"45\\"'
        ' suffix'
    )
    res = cs._extract_douyin_from_render_data(html)
    assert res is not None
    assert res["status"] == "live"
    assert res["online"] == 45
    assert res["title"] == "我的直播间"


def test_extract_render_data_offline():
    html = (
        '\\"id_str\\":\\"123\\",'
        '\\"status\\":4,'
        '\\"title\\":\\"x\\"'
        ',\\"user_count\\":0'
    )
    res = cs._extract_douyin_from_render_data(html)
    assert res is not None
    assert res["status"] == "offline"


def test_extract_render_data_none():
    assert cs._extract_douyin_from_render_data("no douyin data here") is None


def test_extract_share_meta_live():
    html = 'xx shareDesc" value="正在直播" yy shareTitle" value="小明 的直播" zz'
    res = cs._extract_douyin_from_share_meta(html)
    assert res is not None
    assert res["status"] == "live"
    assert "小明" in res["title"]


def test_extract_share_meta_offline():
    html = 'some text 直播已结束 more'
    res = cs._extract_douyin_from_share_meta(html)
    assert res is not None
    assert res["status"] == "offline"


def test_extract_page_text_live():
    html = "正在直播 直播中 观看人数 100"
    res = cs._extract_douyin_from_page_text(html)
    assert res["status"] == "live"


def test_extract_page_text_offline():
    html = "该主播暂无直播 直播已结束"
    res = cs._extract_douyin_from_page_text(html)
    assert res["status"] == "offline"


def test_extract_page_text_unknown():
    html = "随便一段没有关键词的文字"
    assert cs._extract_douyin_from_page_text(html) is None


def test_extract_nickname_from_meta():
    html = '<meta property="og:title" content="老王 的直播">'
    assert cs._extract_douyin_nickname(html) == "老王"


# ==================== load_config ====================

def test_load_config(tmp_path, monkeypatch):
    rooms = [{"platform": "bilibili", "id": "1", "name": "a"}]
    rooms_file = tmp_path / "rooms.json"
    rooms_file.write_text(json.dumps(rooms), encoding="utf-8")
    monkeypatch.setattr(cs, "ROOMS_FILE", str(rooms_file))
    monkeypatch.setenv("BLIVE_CONFIG", '{"push": {"type": "bark", "url": "https://api.day.app/K"}}')
    cfg = cs.load_config()
    assert cfg["rooms"] == rooms
    assert cfg["push_cfg"]["type"] == "bark"


def test_load_config_legacy_sendkey(tmp_path, monkeypatch):
    rooms_file = tmp_path / "rooms.json"
    rooms_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(cs, "ROOMS_FILE", str(rooms_file))
    monkeypatch.setenv("BLIVE_CONFIG", '{"sendkey": "SCT1"}')
    cfg = cs.load_config()
    assert cfg["push_cfg"] == {"type": "serverchan", "sendkey": "SCT1"}


def test_bjnow_is_naive():
    dt = cs.bjnow()
    assert dt.tzinfo is None


def test_bili_status_on_batch_failure():
    assert cs.bili_status_on_batch_failure("live") == "live"
    assert cs.bili_status_on_batch_failure("offline") == "offline"
    assert cs.bili_status_on_batch_failure(None) == "unknown"


def test_main_preserves_prev_on_bili_batch_failure(tmp_path, monkeypatch):
    """B站批量接口整体失败时，沿用上次状态而非误标 error。"""
    rooms = [{"platform": "bilibili", "id": "123", "name": "测试"}]
    rooms_file = tmp_path / "rooms.json"
    rooms_file.write_text(json.dumps(rooms), encoding="utf-8")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"bilibili_123": "live"}), encoding="utf-8")

    monkeypatch.setattr(cs, "ROOMS_FILE", str(rooms_file))
    monkeypatch.setattr(cs, "STATE_FILE", str(state_file))
    monkeypatch.setattr(cs, "TRACKING_FILE", str(tmp_path / "tracking.json"))
    monkeypatch.setattr(cs, "HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setattr(cs, "STATUS_FILE", str(tmp_path / "status.json"))
    monkeypatch.setenv("BLIVE_CONFIG", "{}")
    monkeypatch.setattr(cs, "fetch_bilibili_batch", lambda ids: (_ for _ in ()).throw(RuntimeError("风控")))

    cs.main()

    new_state = json.loads(state_file.read_text(encoding="utf-8"))
    assert new_state.get("bilibili_123") == "live"  # 沿用，不误标 error


def test_main_inherits_prev_fields_on_bili_batch_failure(tmp_path, monkeypatch):
    """B站批量接口整体失败时，沿用上次房间信息（title/online/area）而非清空看板。"""
    rooms = [{"platform": "bilibili", "id": "123", "name": "测试"}]
    rooms_file = tmp_path / "rooms.json"
    rooms_file.write_text(json.dumps(rooms), encoding="utf-8")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"bilibili_123": "live"}), encoding="utf-8")
    status_file = tmp_path / "status.json"
    status_file.write_text(
        json.dumps({
            "updated": "2026-07-08 00:00:00",
            "rooms": [{
                "platform": "bilibili", "id": "123", "name": "测试",
                "status": "live", "title": "旧标题", "online": 42, "area": "电子竞技",
            }],
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(cs, "ROOMS_FILE", str(rooms_file))
    monkeypatch.setattr(cs, "STATE_FILE", str(state_file))
    monkeypatch.setattr(cs, "TRACKING_FILE", str(tmp_path / "tracking.json"))
    monkeypatch.setattr(cs, "HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setattr(cs, "STATUS_FILE", str(status_file))
    monkeypatch.setenv("BLIVE_CONFIG", "{}")
    monkeypatch.setattr(cs, "fetch_bilibili_batch", lambda ids: (_ for _ in ()).throw(RuntimeError("风控")))

    cs.main()

    new_status = json.loads(status_file.read_text(encoding="utf-8"))
    room = next(r for r in new_status["rooms"] if r["id"] == "123")
    assert room["status"] == "live"
    assert room["title"] == "旧标题"
    assert room["online"] == 42
    assert room["area"] == "电子竞技"


def test_main_detects_live_on_recovery(tmp_path, monkeypatch):
    """批量失败期间房间为 offline，恢复后真正开播应正常转为 live。"""
    rooms = [{"platform": "bilibili", "id": "123", "name": "测试"}]
    rooms_file = tmp_path / "rooms.json"
    rooms_file.write_text(json.dumps(rooms), encoding="utf-8")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"bilibili_123": "offline"}), encoding="utf-8")

    monkeypatch.setattr(cs, "ROOMS_FILE", str(rooms_file))
    monkeypatch.setattr(cs, "STATE_FILE", str(state_file))
    monkeypatch.setattr(cs, "TRACKING_FILE", str(tmp_path / "tracking.json"))
    monkeypatch.setattr(cs, "HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setattr(cs, "STATUS_FILE", str(tmp_path / "status.json"))
    monkeypatch.setenv("BLIVE_CONFIG", "{}")
    sample = {"code": 0, "data": {"by_room_ids": {"123": {"live_status": 1, "title": "x", "online": 1}}}}
    monkeypatch.setattr(cs, "fetch_bilibili_batch", lambda ids: sample["data"]["by_room_ids"])

    cs.main()

    status = json.loads(state_file.read_text(encoding="utf-8"))
    assert status.get("bilibili_123") == "live"


# ==================== 日志模块重构：rid 字段 / 级联清理 / HISTORY_MAX 单一来源 ====================

def test_history_max_imported_from_log_utils():
    import log_utils
    # 单一来源：check_status 与 log_utils 引用同一常量对象
    assert cs.HISTORY_MAX == 500
    assert cs.HISTORY_MAX is log_utils.HISTORY_MAX


def test_log_entry_carries_rid_and_orphan_pruned(tmp_path, monkeypatch):
    """固化阶段：history 条目带 rid，且已删房间（rooms 中不存在）的孤儿被级联清除。"""
    rooms = [{"platform": "bilibili", "id": "123", "name": "A"}]
    rooms_file = tmp_path / "rooms.json"
    rooms_file.write_text(json.dumps(rooms), encoding="utf-8")

    # 预置历史：一条已删房间孤儿（rid=999，rooms 无此房间）+ 一条仍存在的（rid=123）
    history_file = tmp_path / "history.json"
    history_file.write_text(json.dumps([
        {"time": "2025-01-01 00:00", "name": "Ghost", "platform": "bilibili", "rid": "999", "status": "offline"},
        {"time": "2025-01-01 00:01", "name": "A", "platform": "bilibili", "rid": "123", "status": "offline"},
    ]), encoding="utf-8")

    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"bilibili_123": "offline"}), encoding="utf-8")

    monkeypatch.setattr(cs, "ROOMS_FILE", str(rooms_file))
    monkeypatch.setattr(cs, "STATE_FILE", str(state_file))
    monkeypatch.setattr(cs, "TRACKING_FILE", str(tmp_path / "tracking.json"))
    monkeypatch.setattr(cs, "HISTORY_FILE", str(history_file))
    monkeypatch.setattr(cs, "STATUS_FILE", str(tmp_path / "status.json"))
    monkeypatch.setenv("BLIVE_CONFIG", "{}")
    sample = {"code": 0, "data": {"by_room_ids": {"123": {"live_status": 1, "title": "x", "online": 1}}}}
    monkeypatch.setattr(cs, "fetch_bilibili_batch", lambda ids: sample["data"]["by_room_ids"])

    cs.main()

    hist = json.loads(history_file.read_text(encoding="utf-8"))
    # 所有条目都带 rid 字段（新增字段，向后兼容）
    assert all("rid" in e for e in hist)
    # 孤儿（rid=999，rooms 中不存在）被级联清除
    assert not any(e.get("rid") == "999" for e in hist)
    # 仍存在的房间（rid=123）历史保留，且包含本轮新写入条目
    assert sum(1 for e in hist if e.get("rid") == "123") >= 1
