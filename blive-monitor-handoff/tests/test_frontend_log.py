"""前端日志面板结构性测试：monitor.html 含功能化元素，三兄弟为重定向壳。"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(REPO, name), encoding="utf-8") as f:
        return f.read()


def test_monitor_has_stats_and_filter():
    html = _read("monitor.html")
    assert 'id="logStats"' in html
    assert 'id="logFilter"' in html
    assert 'id="logAccount"' in html
    assert "onLoadMore" in html
    assert "computeStatsJS" in html
    assert "applyFilters" in html
    assert "toggleExpand" in html
    assert "readViewParam" in html


def test_monitor_no_hardcoded_80_truncation():
    html = _read("monitor.html")
    # 旧实现硬编码 hist.length-80 / -60 截断应已移除
    assert "hist.length-80" not in html
    assert "hist.length-60" not in html
    # 分页步长 50 由 logState.visible 控制
    assert "visible" in html


def test_monitor_supports_view_param():
    html = _read("monitor.html")
    assert "view=dashboard" in html
    assert "view=feed" in html
    assert "view=hero" in html


def test_brothers_are_redirect_shells():
    for name, target in [
        ("monitor-dashboard.html", "view=dashboard"),
        ("monitor-feed.html", "view=feed"),
        ("monitor-hero.html", "view=hero"),
    ]:
        html = _read(name)
        assert "location.replace" in html, f"{name} 应含 location.replace 重定向"
        assert target in html, f"{name} 应重定向到 {target}"
        # 已删除各自重复的日志渲染函数（D 类清理）
        assert "renderLog(" not in html
        assert "renderFeed(" not in html
        assert "renderLogBox(" not in html
