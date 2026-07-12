"""阶段二 2c C2 · 更长趋势：Python 参考实现 + grep 契约。

applyTrendRange(N) 复用 computeStatsJS(hist, N)；daysCovered（hist 中不同 YYYY-MM-DD 数）
< N 时显示「数据不足 N 天」提示（不报错）。边界：恰好 =N 算足够（不提示）。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")


def _src():
    return open(HTML, encoding="utf-8").read()


# ---------------------------------------------------------------------------
# grep 契约
# ---------------------------------------------------------------------------
def test_c2_grep_contracts():
    src = _src()
    for token in ["function applyTrendRange", "trendRange", "数据不足",
                  "computeStatsJS", "trendDays"]:
        assert token in src, "monitor.html 缺少 C2 契约标记: %s" % token


# ---------------------------------------------------------------------------
# Python 参考实现
# ---------------------------------------------------------------------------
def days_covered(hist):
    s = set()
    for e in (hist or []):
        if e.get("time"):
            s.add(str(e["time"])[:10])
    return len(s)


def trend_sufficient(hist, n):
    """daysCovered >= n 才算足够（恰好 =n 也算足够）。"""
    return days_covered(hist) >= n


def _ev(time_str, typ="live_on"):
    return {"type": typ, "time": time_str}


def test_days_covered_counts_distinct_dates():
    hist = [
        _ev("2026-07-01 10:00:00"),
        _ev("2026-07-01 22:00:00"),   # 同日，不重复
        _ev("2026-07-02 10:00:00"),
        _ev("2026-07-03 10:00:00"),
    ]
    assert days_covered(hist) == 3


def test_trend_sufficient_boundary():
    hist = [_ev("2026-07-0%d 10:00:00" % d) for d in range(1, 4)]  # 3 天
    assert days_covered(hist) == 3
    assert trend_sufficient(hist, 7) is False     # 3 < 7 -> 数据不足
    assert trend_sufficient(hist, 3) is True      # 恰好 =3 -> 足够（不提示）


def test_trend_sufficient_empty():
    assert trend_sufficient([], 7) is False
    assert days_covered([]) == 0


def test_trend_sufficient_exact_90():
    hist = [_ev("2026-04-%02d 10:00:00" % d) for d in range(1, 31)]   # 30 天
    hist += [_ev("2026-05-%02d 10:00:00" % d) for d in range(1, 31)]  # +30 天
    hist += [_ev("2026-06-%02d 10:00:00" % d) for d in range(1, 31)]  # +30 天 = 90
    assert days_covered(hist) == 90
    assert trend_sufficient(hist, 90) is True
    assert trend_sufficient(hist, 91) is False
