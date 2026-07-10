"""merge_state 单元测试：验证本地与远端状态文件的语义合并逻辑。

核心场景：CI 持久化失败后，远端有本地丢失的去重记录 → 合并后恢复。
"""
import json
import os

import pytest

# merge_state 不在 tests/ 的 sys.path 中，需要手动导入
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "merge_state",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "merge_state.py"),
)
ms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ms)


# ---------- notify_dedup 合并 ----------

def test_dedup_union_of_keys():
    """本地 + 远端取并集，绝不丢失任何去重记录。"""
    local = {"post:A:1": {"ts": 100}, "post:B:2": {"ts": 200}}
    remote = {"post:A:1": {"ts": 90}, "post:C:3": {"ts": 300}}
    merged = ms.merge_notify_dedup(local, remote)
    assert set(merged.keys()) == {"post:A:1", "post:B:2", "post:C:3"}


def test_dedup_earliest_ts_wins():
    """同一 key 保留更早的 ts（首次推送时间）。"""
    local = {"post:A:1": {"ts": 100}}
    remote = {"post:A:1": {"ts": 90}}
    merged = ms.merge_notify_dedup(local, remote)
    assert merged["post:A:1"]["ts"] == 90


def test_dedup_local_only_preserved():
    local = {"post:B:2": {"ts": 200}}
    remote = {}
    merged = ms.merge_notify_dedup(local, remote)
    assert "post:B:2" in merged


def test_dedup_remote_only_merged():
    """远端独有的 key 必须合并进来（CI 持久化失败恢复的核心）。"""
    local = {}
    remote = {"post:C:3": {"ts": 300}}
    merged = ms.merge_notify_dedup(local, remote)
    assert "post:C:3" in merged


def test_dedup_empty_both():
    assert ms.merge_notify_dedup({}, {}) == {}


# ---------- post_tracking 合并 ----------

def test_tracking_newer_baseline_wins():
    """每个账号取基线更新的那份（aweme_id 数值更大）。"""
    local = {"douyin_A": {"sec_uid": "S", "latest_aweme_id": "100", "mode": "api", "nickname": "A"}}
    remote = {"douyin_A": {"sec_uid": "S", "latest_aweme_id": "050", "mode": "api", "nickname": ""}}
    merged = ms.merge_post_tracking(local, remote)
    assert merged["douyin_A"]["latest_aweme_id"] == "100"


def test_tracking_remote_only_merged():
    local = {}
    remote = {"douyin_C": {"sec_uid": "S", "latest_aweme_id": "300", "mode": "api", "nickname": "C"}}
    merged = ms.merge_post_tracking(local, remote)
    assert "douyin_C" in merged
    assert merged["douyin_C"]["latest_aweme_id"] == "300"


def test_tracking_preserves_nickname():
    local = {"douyin_A": {"sec_uid": "S", "latest_aweme_id": "100", "mode": "api", "nickname": "阿伟"}}
    remote = {"douyin_A": {"sec_uid": "S", "latest_aweme_id": "050", "mode": "api", "nickname": ""}}
    merged = ms.merge_post_tracking(local, remote)
    assert merged["douyin_A"]["nickname"] == "阿伟"


def test_tracking_count_mode_comparison():
    """count 模式：取更大的 count 值。"""
    local = {"douyin_D": {"sec_uid": "S", "latest_aweme_id": "count:64", "mode": "count", "latest_ct": 64}}
    remote = {"douyin_D": {"sec_uid": "S", "latest_aweme_id": "count:63", "mode": "count", "latest_ct": 63}}
    merged = ms.merge_post_tracking(local, remote)
    assert merged["douyin_D"]["latest_aweme_id"] == "count:64"


def test_tracking_remote_newer_wins():
    """远端基线更新时取远端。"""
    local = {"douyin_A": {"sec_uid": "S", "latest_aweme_id": "100", "mode": "api"}}
    remote = {"douyin_A": {"sec_uid": "S", "latest_aweme_id": "200", "mode": "api", "nickname": "新名"}}
    merged = ms.merge_post_tracking(local, remote)
    assert merged["douyin_A"]["latest_aweme_id"] == "200"
    assert merged["douyin_A"]["nickname"] == "新名"


# ---------- post_rooms 合并 ----------

def test_rooms_union_by_id():
    local = [{"id": "A", "name": "A", "sec_uid": "SA"}]
    remote = [{"id": "B", "name": "B", "sec_uid": "SB"}]
    merged = ms.merge_post_rooms(local, remote)
    ids = {r["id"] for r in merged}
    assert ids == {"A", "B"}


def test_rooms_sec_uid_filled_from_local():
    local = [{"id": "A", "name": "A", "sec_uid": "SA"}]
    remote = [{"id": "A", "name": "old", "sec_uid": ""}]
    merged = ms.merge_post_rooms(local, remote)
    a = next(r for r in merged if r["id"] == "A")
    assert a["sec_uid"] == "SA"


def test_rooms_sec_uid_filled_from_remote():
    local = [{"id": "A", "name": "A", "sec_uid": ""}]
    remote = [{"id": "A", "name": "old", "sec_uid": "SA"}]
    merged = ms.merge_post_rooms(local, remote)
    a = next(r for r in merged if r["id"] == "A")
    assert a["sec_uid"] == "SA"


# ---------- history 合并 ----------

def test_history_dedup_by_time_name():
    local = [{"time": "2025-01-01 10:00", "name": "A", "platform": "douyin"}]
    remote = [
        {"time": "2025-01-01 09:00", "name": "C", "platform": "douyin"},
        {"time": "2025-01-01 10:00", "name": "A", "platform": "douyin"},  # 重复
    ]
    merged = ms.merge_history(local, remote)
    assert len(merged) == 2


def test_history_capped():
    local = [{"time": f"2025-01-01 {i:02d}:00", "name": str(i), "platform": "douyin"} for i in range(600)]
    merged = ms.merge_history(local, [])
    assert len(merged) <= ms.HISTORY_MAX
