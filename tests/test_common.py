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
