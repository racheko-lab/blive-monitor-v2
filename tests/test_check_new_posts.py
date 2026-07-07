"""check_new_posts 单元测试：导入可行性、模块复用 common、新作品基线判定（纯函数）。"""
import pytest

import check_new_posts as cnp


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
