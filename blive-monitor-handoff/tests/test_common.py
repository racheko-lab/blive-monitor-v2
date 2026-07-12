"""common 模块单元测试。"""
import json

import common


def test_bjnow_naive():
    dt = common.bjnow()
    assert dt.tzinfo is None


def test_load_save_roundtrip(tmp_path):
    f = tmp_path / "c.json"
    common.save_json_file(str(f), {"k": [1, 2, 3]})
    assert common.load_json_file(str(f)) == {"k": [1, 2, 3]}


def test_load_missing_default(tmp_path):
    assert common.load_json_file(str(tmp_path / "nope.json"), []) == []


def test_load_corrupt(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{broken", encoding="utf-8")
    assert common.load_json_file(str(f), {"d": 1}) == {"d": 1}


def test_beijing_tz_offset():
    # UTC+8
    assert common.BEIJING_TZ.utcoffset(None).total_seconds() == 8 * 3600


def test_default_user_agent():
    assert "Chrome" in common.DEFAULT_USER_AGENT


def test_save_json_file_atomic_no_tmp_leftover(tmp_path):
    """原子写：最终文件内容正确，且不应留下 .tmp 残留文件。"""
    f = tmp_path / "status.json"
    common.save_json_file(str(f), {"rooms": [{"id": 1}]})
    assert json.loads(f.read_text(encoding="utf-8")) == {"rooms": [{"id": 1}]}
    assert not (tmp_path / "status.json.tmp").exists()


def test_save_json_file_overwrites_atomically(tmp_path):
    """覆盖写也能正确更新内容（os.replace 原子替换）。"""
    f = tmp_path / "status.json"
    common.save_json_file(str(f), {"v": 1})
    common.save_json_file(str(f), {"v": 2})
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": 2}
    assert not (tmp_path / "status.json.tmp").exists()

