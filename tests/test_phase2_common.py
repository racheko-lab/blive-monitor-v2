"""阶段二 2a · 通用纯函数：inSilence（A3 预留，2a 仅签名 + 参考测试）。

inSilence 用于「静默时段」判定（支持跨午夜）。2a 阶段仅在 monitor.html 落签名与
参考测试，真正配置 UI / CI 消费属 2b。此处验证参考实现与 grep 契约。
"""
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")


def _src():
    return open(HTML, encoding="utf-8").read()


def test_inSilence_function_present():
    assert "function inSilence" in _src(), "monitor.html 缺少 inSilence 函数"


def in_silence(now_bj, silence):
    """镜像 JS inSilence（参考实现）。"""
    if not silence or not silence.get("enabled"):
        return False

    def hm(s):
        p = str(s or "00:00").split(":")
        h = int(p[0] or "0") if p[0].isdigit() else 0
        m = int(p[1] or "0") if len(p) > 1 and p[1].isdigit() else 0
        return h * 60 + m

    start = hm(silence.get("start"))
    end = hm(silence.get("end"))
    cur = now_bj.hour * 60 + now_bj.minute
    if start <= end:
        return start <= cur < end
    return cur >= start or cur < end  # 跨午夜


def test_inSilence_disabled():
    assert in_silence(datetime(2026, 7, 11, 23, 30), {"enabled": False, "start": "23:00", "end": "08:00"}) is False


def test_inSilence_within_range():
    silence = {"enabled": True, "start": "23:00", "end": "08:00"}
    assert in_silence(datetime(2026, 7, 11, 23, 30), silence) is True   # 跨午夜内
    assert in_silence(datetime(2026, 7, 11, 7, 30), silence) is True    # 次晨内
    assert in_silence(datetime(2026, 7, 11, 12, 0), silence) is False   # 白天不在内


def test_inSilence_no_cross_midnight():
    silence = {"enabled": True, "start": "09:00", "end": "18:00"}
    assert in_silence(datetime(2026, 7, 11, 12, 0), silence) is True
    assert in_silence(datetime(2026, 7, 11, 20, 0), silence) is False
