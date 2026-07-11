"""阶段二 2b · A3 静默时段：CI 拦截 + 前端配置 UI + Python 参考实现。

grep 契约：
  - monitor.html 必须含 silenceEnabled / silenceStart / silenceEnd / silenceHint
    （控件 id）与 inSilence / buildSilenceConfig / loadSilenceUI /
    renderSilenceHint / saveSilenceConfig（函数名）。
  - check_status.py 与 check_new_posts.py 必须含 should_skip_by_silence 调用
    （CI 推送前拦截）。
  - 仓库根存在可读镜像 silence_state.json（前端拥有，供回显 / 当前是否静默）。

Python 参考实现镜像 JS inSilence（common.in_silence），并用跨午夜等用例验证；
同时验证 common.should_skip_by_silence / common.load_silence_cfg。
"""
import os
import json
from datetime import datetime

import common

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")
CHECK_STATUS = os.path.join(ROOT, "check_status.py")
CHECK_POSTS = os.path.join(ROOT, "check_new_posts.py")
SILENCE_STATE = os.path.join(ROOT, "silence_state.json")


# ---------------------------------------------------------------------------
# grep 契约
# ---------------------------------------------------------------------------
def test_html_silence_contract():
    src = open(HTML, encoding="utf-8").read()
    for token in [
        "silenceEnabled", "silenceStart", "silenceEnd", "silenceHint",
        "inSilence", "buildSilenceConfig", "loadSilenceUI",
        "renderSilenceHint", "saveSilenceConfig",
    ]:
        assert token in src, f"monitor.html 缺少 A3 契约标记: {token}"


def test_ci_should_skip_by_silence_grep():
    cs = open(CHECK_STATUS, encoding="utf-8").read()
    assert "should_skip_by_silence" in cs, "check_status.py 未含 should_skip_by_silence 拦截"
    cp = open(CHECK_POSTS, encoding="utf-8").read()
    assert "should_skip_by_silence" in cp, "check_new_posts.py 未含 should_skip_by_silence 拦截"


def test_silence_state_json_exists():
    assert os.path.exists(SILENCE_STATE), "仓库根缺少 silence_state.json 可读镜像"
    st = json.load(open(SILENCE_STATE, encoding="utf-8"))
    for k in ("enabled", "start", "end"):
        assert k in st, f"silence_state.json 缺字段: {k}"


# ---------------------------------------------------------------------------
# Python 参考实现（镜像 JS inSilence）
# ---------------------------------------------------------------------------
def test_in_silence_disabled():
    assert common.in_silence(
        datetime(2026, 7, 11, 23, 30),
        {"enabled": False, "start": "23:00", "end": "08:00"},
    ) is False


def test_in_silence_cross_midnight():
    silence = {"enabled": True, "start": "23:00", "end": "08:00"}
    assert common.in_silence(datetime(2026, 7, 11, 23, 30), silence) is True   # 跨午夜内
    assert common.in_silence(datetime(2026, 7, 11, 7, 30), silence) is True    # 次晨内
    assert common.in_silence(datetime(2026, 7, 11, 12, 0), silence) is False  # 白天


def test_in_silence_no_cross_midnight():
    silence = {"enabled": True, "start": "09:00", "end": "18:00"}
    assert common.in_silence(datetime(2026, 7, 11, 12, 0), silence) is True
    assert common.in_silence(datetime(2026, 7, 11, 20, 0), silence) is False


def test_should_skip_by_silence():
    silence = {"enabled": True, "start": "23:00", "end": "08:00"}
    assert common.should_skip_by_silence(
        datetime(2026, 7, 11, 23, 30), silence
    ) is True
    assert common.should_skip_by_silence(
        datetime(2026, 7, 11, 12, 0), silence
    ) is False
    # 未静默配置（{}）不跳过
    assert common.should_skip_by_silence(
        datetime(2026, 7, 11, 23, 30), {}
    ) is False


def test_load_silence_cfg():
    raw = '{"push": {"type": "bark", "url": "u"}, ' \
          '"silence": {"enabled": true, "start": "23:00", "end": "08:00"}}'
    cfg = common.load_silence_cfg(raw)
    assert cfg == {"enabled": True, "start": "23:00", "end": "08:00"}, cfg
    # 无 silence 段 → {}
    assert common.load_silence_cfg('{"push": {"type": "bark"}}') == {}
    # 非法 JSON → {}
    assert common.load_silence_cfg("{not json") == {}
