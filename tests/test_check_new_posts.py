"""check_new_posts 单元测试：导入可行性、模块复用 common、新作品基线判定（纯函数）。"""
import json
import sys
import types

import pytest

import check_new_posts as cnp


# ---------- 假 Playwright：让 main() 的惰性 import 可用，无需真实浏览器 ----------
class _FakeContext:
    def close(self):
        pass


class _FakeBrowser:
    def new_context(self, **kwargs):
        return _FakeContext()

    def close(self):
        pass


class _FakePW:
    def __init__(self):
        self.chromium = types.SimpleNamespace(launch=lambda **kw: _FakeBrowser())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_fake_playwright():
    """注入假的 playwright.sync_api 模块，使 main() 的 `from playwright... import` 成功。"""
    if "playwright" not in sys.modules:
        sys.modules["playwright"] = types.ModuleType("playwright")
    fake = types.ModuleType("playwright.sync_api")
    fake.sync_playwright = lambda: _FakePW()
    sys.modules["playwright.sync_api"] = fake


def test_module_imports_common():
    # 复用 common 的 bjnow / load_json_file / save_json_file
    assert hasattr(cnp, "bjnow")
    assert hasattr(cnp, "load_json_file")
    assert hasattr(cnp, "save_json_file")


def test_push_utils_imported():
    assert hasattr(cnp, "dispatch_push")
    assert hasattr(cnp, "load_push_cfg")


@pytest.mark.parametrize("prev_id,prev_ct,new_id,new_ct,expected", [
    ("old", 100, "new", 200, True),     # 确实更新 -> 通知
    ("old", 100, "new", 50, False),     # 接口返回更旧 -> 不误报
    ("same", 100, "same", 200, False),  # 同一作品 -> 不重复通知
    ("", 0, "new", 200, False),         # 首次仅建立基线，不推送（避免启用即轰炸）
    ("old", 100, "new", 100, False),    # 相同时间戳不同 id -> 不通知
])
def test_should_notify_new_post(prev_id, prev_ct, new_id, new_ct, expected):
    assert cnp.should_notify_new_post(prev_id, prev_ct, new_id, new_ct) is expected


@pytest.mark.parametrize("prev_ct,new_ct,expected", [
    (100, 200, True),    # 更新基线
    (100, 50, False),    # 更旧 -> 保留旧基线（防接口延迟回退）
    (0, 200, True),      # 首次
    (100, 100, True),    # 持平 -> 更新
])
def test_should_update_baseline(prev_ct, new_ct, expected):
    assert cnp.should_update_baseline(prev_ct, new_ct) is expected


# ==================== main() 端到端（mock 浏览器，真实走流程） ====================

def _seed(tmp_path, monkeypatch, post_rooms, tracking=None, push_cfg='{"push":{"type":"bark","url":"https://api.day.app/K"}}'):
    config_file = tmp_path / "post_rooms.json"
    config_file.write_text(json.dumps(post_rooms), encoding="utf-8")
    tracking_file = tmp_path / "post_tracking.json"
    if tracking is not None:
        tracking_file.write_text(json.dumps(tracking), encoding="utf-8")
    monkeypatch.setattr(cnp, "CONFIG_FILE", str(config_file))
    monkeypatch.setattr(cnp, "TRACKING_FILE", str(tracking_file))
    monkeypatch.setattr(cnp, "resolve_sec_uid", lambda ctx, rid: rid)
    monkeypatch.setenv("ENABLE_POST_CHECK", "true")
    monkeypatch.setenv("BLIVE_CONFIG", push_cfg)
    return tracking_file


def test_main_first_run_establishes_baseline_no_notify(tmp_path, monkeypatch):
    """首次运行仅建立基线，不推送（避免启用即轰炸）。"""
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}])
    calls = []
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: {
        "aweme_id": "999", "desc": "新视频", "video_url": "https://v/999",
        "is_note": False, "nickname": "阿伟", "create_time": 1700000000,
    })

    cnp.main()

    tracking = json.loads(tf.read_text(encoding="utf-8"))
    assert tracking["douyin_MS4wABC"]["latest_aweme_id"] == "999"
    assert tracking["douyin_MS4wABC"]["latest_ct"] == 1700000000
    assert calls == []


def test_main_detects_new_post_and_notifies(tmp_path, monkeypatch):
    """基线已知 888，接口取到更新的 999 → 推送一次且更新基线。"""
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
               tracking={"douyin_MS4wABC": {"sec_uid": "MS4wABC", "latest_aweme_id": "888", "latest_ct": 1699999000}})
    calls = []
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: {
        "aweme_id": "999", "desc": "新视频", "video_url": "https://v/999",
        "is_note": False, "nickname": "阿伟", "create_time": 1700000000,
    })

    cnp.main()

    tracking = json.loads(tf.read_text(encoding="utf-8"))
    assert tracking["douyin_MS4wABC"]["latest_aweme_id"] == "999"
    assert len(calls) == 1
    assert "新作品" in calls[0]


def test_main_feed_lag_keeps_baseline(tmp_path, monkeypatch):
    """接口返回的作品反而更旧（feed 延迟）→ 不误推送、也不回退基线。"""
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
               tracking={"douyin_MS4wABC": {"sec_uid": "MS4wABC", "latest_aweme_id": "888", "latest_ct": 1700000000}})
    calls = []
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: {
        "aweme_id": "777", "desc": "旧视频", "video_url": "https://v/777",
        "is_note": False, "nickname": "阿伟", "create_time": 1699999000,
    })

    cnp.main()

    tracking = json.loads(tf.read_text(encoding="utf-8"))
    assert tracking["douyin_MS4wABC"]["latest_aweme_id"] == "888"   # 基线不变
    assert tracking["douyin_MS4wABC"]["latest_ct"] == 1700000000
    assert calls == []


def test_main_cleans_up_removed_accounts(tmp_path, monkeypatch):
    """监控列表已不含某账号 → 其历史状态被清理。"""
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
               tracking={
                   "douyin_MS4wABC": {"sec_uid": "MS4wABC", "latest_aweme_id": "888", "latest_ct": 1},
                   "douyin_OLD123": {"sec_uid": "MS4wOLD", "latest_aweme_id": "1", "latest_ct": 1},
               },
               push_cfg="{}")
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: {
        "aweme_id": "999", "desc": "x", "video_url": "https://v/999",
        "is_note": False, "nickname": "阿伟", "create_time": 1700000000,
    })

    cnp.main()

    tracking = json.loads(tf.read_text(encoding="utf-8"))
    assert "douyin_MS4wABC" in tracking
    assert "douyin_OLD123" not in tracking
