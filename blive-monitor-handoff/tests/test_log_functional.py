"""日志模块功能性端到端测试。

覆盖：
- type 枚举（单一来源）与 level 推导；
- should_suppress 30min 节流；
- compute_stats 按天聚合；
- 迁移脚本幂等（复用 tools/migrate_history_types）；
- 前端筛选/排序/分页纯函数语义（与 monitor.html 内 JS 算法一致的 Python 镜像回归）；
- 模拟 check_new_posts 写入 new_post / error / cookie_warn 到临时 history，断言节流与字段正确。
"""
import importlib.util
import json
import os
from datetime import datetime

import pytest

import log_utils as lu

# ---- 前端纯函数镜像（与 monitor.html 的 applyFilters / 排序 / 分页语义一致）----
# 仅作算法回归锚点；canonical 实现位于 monitor.html 内联 JS。
def apply_filters(hist, state):
    out = []
    q = state.get("search", "").strip().lower()
    date = state.get("date", "")
    for l in hist:
        t = l.get("type") or l.get("status")
        if state.get("type") != "all" and t != state.get("type"):
            continue
        if state.get("platform") != "all" and l.get("platform") != state.get("platform"):
            continue
        if state.get("account"):
            if (l.get("account") or l.get("rid") or "") != state.get("account"):
                continue
        if date and (l.get("time") or "")[:10] != date:
            continue
        if q:
            hay = ((l.get("name") or "") + " " + (l.get("title") or "") + " " + (l.get("detail") or "")).lower()
            if q not in hay:
                continue
        out.append(l)
    out.sort(key=lambda x: x.get("time") or "", reverse=(state.get("sort", "desc") == "desc"))
    return out


def paginate(items, visible):
    return items[:visible]


# ==================== 枚举 / 推导 ====================

def test_event_type_enum_is_single_source():
    assert lu.EVENT_TYPES == frozenset(
        {"live_on", "live_off", "new_post", "error", "cookie_warn", "system"}
    )


def test_type_and_level_derivation():
    assert lu.type_from_status("live") == "live_on"
    assert lu.type_from_status("offline") == "live_off"
    assert lu.type_from_status(None) == "system"
    assert lu.level_from_type("cookie_warn") == "warn"
    assert lu.level_from_type("error") == "error"
    assert lu.level_from_type("new_post") == "info"


# ==================== 节流 ====================

def test_should_suppress_30min_window(tmp_path):
    p = str(tmp_path / "history.json")
    lu.append_history(p, [{"time": "2026-07-10 10:00:00", "rid": "1", "type": "error"}], 500)
    now_in = datetime(2026, 7, 10, 10, 5)
    now_out = datetime(2026, 7, 10, 10, 35)
    assert lu.should_suppress("1", "error", now_in, history_path=p) is True
    assert lu.should_suppress("1", "error", now_out, history_path=p) is False
    assert lu.should_suppress("1", "cookie_warn", now_in, history_path=p) is False


# ==================== 统计 ====================

def test_compute_stats_aggregation():
    hist = [
        {"time": "2026-07-10 10:00:00", "type": "new_post"},
        {"time": "2026-07-10 11:00:00", "type": "new_post"},
        {"time": "2026-07-10 12:00:00", "type": "live_on"},
        {"time": "2026-07-09 10:00:00", "type": "new_post"},
    ]
    s = lu.compute_stats(hist, days=7, now=datetime(2026, 7, 10, 23, 0))
    assert s["days"][6] == "07-10"
    assert s["new_post"][6] == 2
    assert s["new_post"][5] == 1
    assert s["live_on"][6] == 1
    assert s["totals"]["new_post"] == 3


# ==================== 迁移幂等 ====================

def test_migration_idempotent():
    spec = importlib.util.spec_from_file_location(
        "migrate_history_types",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "migrate_history_types.py"),
    )
    mht = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mht)

    import tempfile
    import pathlib
    d = pathlib.Path(tempfile.mkdtemp())
    p = str(d / "history.json")
    data = [
        {"time": "2026-07-10 10:00", "status": "live"},
        {"time": "2026-07-10 10:01", "status": "error"},
        {"time": "2026-07-10 10:02"},  # 无 status → system
    ]
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps(data))
    mht.run(p)
    h1 = json.loads(open(p, encoding="utf-8").read())
    assert h1[0]["type"] == "live_on"
    assert h1[1]["type"] == "error"
    assert h1[2]["type"] == "system"
    mht.run(p)  # 幂等
    h2 = json.loads(open(p, encoding="utf-8").read())
    assert len(h2) == 3
    assert h2[0]["type"] == "live_on"


# ==================== 前端纯函数（筛选/排序/分页）镜像回归 ====================

def _sample_hist():
    return [
        {"time": "2026-07-10 10:00", "name": "张三", "platform": "bilibili", "type": "live_on", "title": "晚八点live", "rid": "1"},
        {"time": "2026-07-10 11:00", "name": "李四", "platform": "douyin", "type": "new_post", "detail": "新作品x", "rid": "2"},
        {"time": "2026-07-10 12:00", "name": "王五", "platform": "bilibili", "type": "error", "rid": "3"},
    ]


def test_apply_filters_type_and_search():
    hist = _sample_hist()
    r = apply_filters(hist, {"type": "new_post", "platform": "all", "sort": "desc"})
    assert len(r) == 1 and r[0]["name"] == "李四"
    r = apply_filters(hist, {"type": "all", "platform": "bilibili", "sort": "desc"})
    assert len(r) == 2
    r = apply_filters(hist, {"type": "all", "platform": "all", "search": "新作品", "sort": "desc"})
    assert len(r) == 1 and r[0]["name"] == "李四"
    r = apply_filters(hist, {"type": "all", "platform": "all", "search": "晚八", "sort": "desc"})
    assert len(r) == 1 and r[0]["name"] == "张三"
    r = apply_filters(hist, {"type": "all", "platform": "all", "account": "3", "sort": "desc"})
    assert len(r) == 1
    r = apply_filters(hist, {"type": "all", "platform": "all", "date": "2026-07-09", "sort": "desc"})
    assert len(r) == 0


def test_sort_and_pagination():
    hist = [
        {"time": f"2026-07-10 {h:02d}:00", "name": f"n{i}", "platform": "bilibili", "type": "live_on", "rid": str(i)}
        for i, h in enumerate(range(10))
    ]
    desc = apply_filters(hist, {"type": "all", "platform": "all", "sort": "desc"})
    assert desc[0]["time"] == "2026-07-10 09:00"
    asc = apply_filters(hist, {"type": "all", "platform": "all", "sort": "asc"})
    assert asc[0]["time"] == "2026-07-10 00:00"
    assert len(paginate(desc, 5)) == 5


# ==================== 端到端：模拟 check_new_posts 写入 + 节流 ====================

def test_end_to_end_new_post_and_error_throttle(tmp_path):
    p = str(tmp_path / "history.json")
    now = datetime(2026, 7, 10, 10, 0)
    # 模拟 check_new_posts：new_post 始终写入（非错误类）
    lu.append_history(p, lu.dedupe_by_throttle(
        [{"rid": "A", "type": "new_post", "time": "2026-07-10 10:00:00", "name": "阿伟", "platform": "douyin"}],
        now, history_path=p), lu.HISTORY_MAX)
    # 第一次 error（磁盘无近期）→ 保留
    lu.append_history(p, lu.dedupe_by_throttle(
        [{"rid": "A", "type": "error", "time": "2026-07-10 10:00:00"}], now, history_path=p), lu.HISTORY_MAX)
    hist = lu.load_history(p)
    assert any(e["type"] == "new_post" for e in hist)
    assert any(e["type"] == "error" for e in hist)
    # 第二次 error（10 分钟后，窗口内）→ 抑制，不新增
    lu.append_history(p, lu.dedupe_by_throttle(
        [{"rid": "A", "type": "error", "time": "2026-07-10 10:10:00"}], now, history_path=p), lu.HISTORY_MAX)
    hist2 = lu.load_history(p)
    assert sum(1 for e in hist2 if e["type"] == "error") == 1
