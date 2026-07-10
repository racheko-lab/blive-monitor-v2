"""state_prune 单元测试：history/tracking 孤儿清理、post_rooms 字段合并（补丁归一）。"""
import json

import pytest

import state_prune as sp


# ==================== prune_history_orphans ====================

def test_prune_history_orphans_keeps_matching_rid():
    history = [
        {"platform": "bilibili", "rid": "1", "name": "A"},
        {"platform": "douyin", "rid": "9", "name": "B"},
        {"platform": "bilibili", "rid": "2", "name": "C"},  # 孤儿
    ]
    active = {"bilibili|1", "douyin|9"}
    out = sp.prune_history_orphans(history, active)
    assert [e["name"] for e in out] == ["A", "B"]


def test_prune_history_orphans_keeps_legacy_without_rid():
    # 无 rid 的存量条目（重构前写入）保守保留，避免首轮部署即清空全部历史
    history = [
        {"platform": "bilibili", "name": "Old"},
        {"platform": "douyin", "rid": "9", "name": "B"},  # 孤儿（rid 不匹配）
    ]
    active = {"bilibili|1"}
    out = sp.prune_history_orphans(history, active)
    names = {e["name"] for e in out}
    assert "Old" in names  # 存量无 rid 保留
    assert "B" not in names  # 带 rid 孤儿被裁


def test_prune_history_orphans_empty_active_drops_rid_entries():
    history = [{"platform": "bilibili", "rid": "1", "name": "A"}]
    out = sp.prune_history_orphans(history, set())
    # 该条带 rid 且不在 active → 被裁；无 rid 条目才会保留
    assert out == []


def test_prune_history_orphans_returns_new_list():
    history = [{"platform": "bilibili", "rid": "1"}]
    out = sp.prune_history_orphans(history, {"bilibili|1"})
    assert out is not history  # 不应改写入参


# ==================== prune_tracking_orphans ====================

def test_prune_tracking_orphans():
    tracking = {
        "douyin_A": {"latest_aweme_id": "1"},
        "douyin_B": {"latest_aweme_id": "2"},  # 孤儿
        "douyin_C": {"latest_aweme_id": "3"},
    }
    active = {"douyin_A", "douyin_C"}
    out = sp.prune_tracking_orphans(tracking, active)
    assert set(out.keys()) == {"douyin_A", "douyin_C"}


def test_prune_tracking_orphans_returns_new_dict():
    tracking = {"douyin_A": {}}
    out = sp.prune_tracking_orphans(tracking, {"douyin_A"})
    assert out is not tracking


def test_prune_tracking_orphans_preserves_values():
    tracking = {"douyin_A": {"latest_aweme_id": "99"}}
    out = sp.prune_tracking_orphans(tracking, {"douyin_A"})
    assert out["douyin_A"]["latest_aweme_id"] == "99"


# ==================== merge_post_rooms_fields ====================

def test_merge_post_rooms_fields_updates_in_place(tmp_path):
    cfg = tmp_path / "post_rooms.json"
    cfg.write_text(json.dumps([
        {"id": "A", "name": "oldA", "sec_uid": ""},
        {"id": "B", "name": "B", "sec_uid": "SB"},
    ]), encoding="utf-8")
    resolved = {
        "A": {"id": "A", "name": "newA", "sec_uid": "SA"},
        "B": {"id": "B", "name": "B", "sec_uid": "NEW_SB"},
    }
    changed = sp.merge_post_rooms_fields(str(cfg), resolved)
    assert changed is True
    data = json.loads(cfg.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in data}
    assert by_id["A"]["sec_uid"] == "SA"
    assert by_id["A"]["name"] == "newA"
    assert by_id["B"]["sec_uid"] == "NEW_SB"  # B 也按 resolved 更新了 sec_uid


def test_merge_post_rooms_fields_no_revive_deleted(tmp_path):
    # 当前磁盘没有账号 X（前端已删），即使 resolved 含 X，也不应写回（不复活）
    cfg = tmp_path / "post_rooms.json"
    cfg.write_text(json.dumps([
        {"id": "A", "name": "A", "sec_uid": ""},
    ]), encoding="utf-8")
    resolved = {
        "A": {"id": "A", "name": "A", "sec_uid": "SA"},
        "X": {"id": "X", "name": "X", "sec_uid": "SX"},  # 已删账号，不应复活
    }
    changed = sp.merge_post_rooms_fields(str(cfg), resolved)
    assert changed is True
    data = json.loads(cfg.read_text(encoding="utf-8"))
    ids = [e["id"] for e in data]
    assert ids == ["A"]  # X 未复活
    assert data[0]["sec_uid"] == "SA"


def test_merge_post_rooms_fields_no_change_returns_false(tmp_path):
    cfg = tmp_path / "post_rooms.json"
    cfg.write_text(json.dumps([
        {"id": "A", "name": "A", "sec_uid": "SA"},
    ]), encoding="utf-8")
    resolved = {"A": {"id": "A", "name": "A", "sec_uid": "SA"}}  # 完全相同
    changed = sp.merge_post_rooms_fields(str(cfg), resolved)
    assert changed is False


def test_merge_post_rooms_fields_uses_atomic_write(tmp_path):
    # 验证走 common.save_json_file（.tmp + os.replace），无残留 .tmp
    cfg = tmp_path / "post_rooms.json"
    cfg.write_text(json.dumps([{"id": "A", "name": "A", "sec_uid": ""}]), encoding="utf-8")
    sp.merge_post_rooms_fields(str(cfg), {"A": {"id": "A", "name": "A", "sec_uid": "SA"}})
    assert not list(tmp_path.glob("*.tmp"))


def test_merge_post_rooms_fields_name_only(tmp_path):
    # 仅 name 变化也应回写
    cfg = tmp_path / "post_rooms.json"
    cfg.write_text(json.dumps([{"id": "A", "name": "old", "sec_uid": "SA"}]), encoding="utf-8")
    resolved = {"A": {"id": "A", "name": "new", "sec_uid": "SA"}}
    changed = sp.merge_post_rooms_fields(str(cfg), resolved)
    assert changed is True
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data[0]["name"] == "new"
    assert data[0]["sec_uid"] == "SA"
