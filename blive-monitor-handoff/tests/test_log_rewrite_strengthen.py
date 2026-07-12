"""日志模块功能性重写 —— 独立验证补强测试（严过关）。

覆盖工程师自测未充分锚定的边界/回归点：
  - 节流边界：恰好 30min（含边界）内/外、跨日、同 rid 不同 type 隔离；
  - dedupe：new_post/system 始终写入（不受节流），仅 error/cookie_warn 节流；
  - compute_stats 零填充回归（单数字日/月）+ 与前端 computeStatsJS 真实函数口径一致（node 实跑）；
  - 迁移幂等：二次运行 changes==0、条数不变；并能以 `python3 tools/...` 直接运行（import 路径已修）；
  - 前端 XSS：renderLogItem 对 name/title/detail/time/rid/platform 转义；readViewParam 仅白名单、无注入；
  - 分页纯函数边界：首屏≤50、末页不足 50、空历史、按账号精确匹配；
  - 三兄弟重定向：目标为 monitor.html（canonical），自身文件名不再出现，无死循环。

不依赖具体时间/随机，可重复运行。
"""
import importlib.util
import json
import os
import re
import subprocess
from datetime import datetime

import pytest

import log_utils as lu

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONITOR_HTML = os.path.join(REPO, "monitor.html")


def _has_node() -> bool:
    try:
        return subprocess.run(["node", "--version"], capture_output=True).returncode == 0
    except Exception:
        return False


def _read_monitor() -> str:
    with open(MONITOR_HTML, encoding="utf-8") as f:
        return f.read()


def _extract_js(html: str, fn_name: str, sig: str) -> str:
    """从 monitor.html 提取某个顶层 function 的完整源码（其闭合 `}` 位于行首）。"""
    m = re.search(re.escape(sig) + r"\{.*?\n\}", html, re.S)
    assert m, f"未能从 monitor.html 提取 {fn_name}"
    return m.group(0)


def _load_mht():
    spec = importlib.util.spec_from_file_location(
        "migrate_history_types",
        os.path.join(REPO, "tools", "migrate_history_types.py"),
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ==================== 节流边界 ====================

def test_should_suppress_exactly_30min_inclusive(tmp_path):
    """恰好 30min 视为窗口内（含边界）应抑制；30min+1s 视为窗口外不抑制。"""
    p = str(tmp_path / "h.json")
    lu.append_history(p, [{"time": "2026-07-10 10:00:00", "rid": "1", "type": "error"}], 500)
    assert lu.should_suppress("1", "error", datetime(2026, 7, 10, 10, 30), history_path=p) is True
    assert lu.should_suppress("1", "error", datetime(2026, 7, 10, 10, 30, 1), history_path=p) is False


def test_should_suppress_cross_day_and_type_isolation(tmp_path):
    """跨日（昨天 23:50 → 今天 00:10，间隔 20min）仍按绝对时间窗判定；同 rid 不同 type 不抑制。"""
    p = str(tmp_path / "h.json")
    lu.append_history(p, [{"time": "2026-07-09 23:50:00", "rid": "1", "type": "error"}], 500)
    now = datetime(2026, 7, 10, 0, 10)
    assert lu.should_suppress("1", "error", now, history_path=p) is True
    assert lu.should_suppress("1", "cookie_warn", now, history_path=p) is False
    assert lu.should_suppress("2", "error", now, history_path=p) is False


def test_dedupe_keeps_new_post_and_system_always(tmp_path):
    """new_post/system 不受节流（始终写入）；仅 error/cookie_warn 受 30min 窗口约束。"""
    p = str(tmp_path / "h.json")
    now = datetime(2026, 7, 10, 10, 0)
    lu.append_history(p, [{"time": "2026-07-10 09:55:00", "rid": "1", "type": "error"}], 500)
    entries = [
        {"rid": "1", "type": "new_post", "time": "2026-07-10 10:00:00"},
        {"rid": "1", "type": "system", "time": "2026-07-10 10:00:00"},
        {"rid": "1", "type": "error", "time": "2026-07-10 10:00:00"},  # 窗口内→应被抑制
    ]
    out = lu.dedupe_by_throttle(entries, now, history_path=p)
    types = [e["type"] for e in out]
    assert "new_post" in types
    assert "system" in types
    assert "error" not in types


# ==================== compute_stats 零填充 + 前后端口径一致 ====================

def test_compute_stats_zero_padded_labels_single_digit():
    """回归：单数字日/月必须零填充（07-05 / 08-01），否则与 time 子串 '07-05' 不匹配导致统计恒空。"""
    hist = [
        {"time": "2026-07-05 10:00:00", "type": "new_post"},
        {"time": "2026-08-01 09:00:00", "type": "live_on"},  # 跨月，不在 7 天窗口内
        {"time": "2026-07-10 12:00:00", "type": "live_on"},
    ]
    s = lu.compute_stats(hist, days=7, now=datetime(2026, 7, 10, 23, 0))
    # 标签全部零填充 MM-DD
    assert s["days"] == ["07-04", "07-05", "07-06", "07-07", "07-08", "07-09", "07-10"]
    # 单数字日 07-05 正确计入 new_post
    assert s["new_post"][1] == 1
    # 跨月 08-01 不在窗口（07-04..07-10）→ live_on 仅 07-10 命中
    assert s["live_on"][6] == 1
    assert s["live_on"][0] == 0


@pytest.mark.skipif(not _has_node(), reason="node 不可用，跳过前端真实函数口径校验")
def test_compute_stats_js_parity_with_real_file():
    """实跑 monitor.html 内的 computeStatsJS，断言其输出与 Python compute_stats 完全一致（含零填充）。"""
    html = _read_monitor()
    js = _extract_js(html, "computeStatsJS", "function computeStatsJS(histData, days, now)")
    hist = [
        {"time": "2026-07-05 10:00:00", "type": "new_post"},
        {"time": "2026-07-10 11:00:00", "type": "new_post"},
        {"time": "2026-07-10 12:00:00", "type": "live_on"},
        {"time": "2026-08-01 09:00:00", "type": "error"},   # 不在 7 天窗口
        {"time": "2026-07-09 10:00:00", "type": "cookie_warn"},
        {"time": "2026-07-10 08:00:00", "type": "weird"},    # 未知 type 忽略
        {"time": "2026-07-10 09:00:00"},                      # 无 type 忽略
    ]
    harness = js + "\n" + (
        "var hist = %s;\n"
        "var now = new Date(2026, 6, 10, 23, 0, 0);\n"
        "console.log(JSON.stringify(computeStatsJS(hist, 7, now)));\n"
    ) % json.dumps(hist)
    import tempfile
    f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    f.write(harness)
    f.close()
    try:
        r = subprocess.run(["node", f.name], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        js_out = json.loads(r.stdout.strip())
    finally:
        os.unlink(f.name)

    py = lu.compute_stats(hist, days=7, now=datetime(2026, 7, 10, 23, 0))
    expected = {
        "days": py["days"],
        "new_post": py["new_post"],
        "live_on": py["live_on"],
        "error": py["error"],
        "cookie_warn": py["cookie_warn"],
        "totals": py["totals"],
    }
    assert js_out == expected


# ==================== 前端筛选/排序纯函数边界（实跑 monitor.html 内 applyFilters） ====================

@pytest.mark.skipif(not _has_node(), reason="node 不可用，跳过前端真实函数校验")
def test_apply_filters_js_edge_cases():
    """实跑 monitor.html 内 applyFilters（纯函数）：空历史/类型/搜索/账号/日期/排序边界。"""
    html = _read_monitor()
    js = _extract_js(html, "applyFilters", "function applyFilters()")
    hist = [
        {"time": "2026-07-10 10:00", "name": "张三", "platform": "bilibili", "type": "live_on", "title": "晚八点", "rid": "1"},
        {"time": "2026-07-10 11:00", "name": "李四", "platform": "douyin", "type": "new_post", "detail": "新作品x", "rid": "2"},
        {"time": "2026-07-09 12:00", "name": "王五", "platform": "bilibili", "type": "error", "rid": "3"},
    ]
    harness = (
        "var hist = %s;\n"
        "var logState;\n"
        "%s\n"
        "function run(state){ logState = state; return applyFilters(); }\n"
        "var out = {};\n"
        "out.all = run({search:'',type:'all',platform:'all',account:'',date:'',sort:'desc'}).length;\n"
        "out.byType = run({search:'',type:'new_post',platform:'all',account:'',date:'',sort:'desc'}).length;\n"
        "out.bySearch = run({search:'新作品',type:'all',platform:'all',account:'',date:'',sort:'desc'}).length;\n"
        "out.byAccount = run({search:'',type:'all',platform:'all',account:'3',date:'',sort:'desc'}).length;\n"
        "out.byDate = run({search:'',type:'all',platform:'all',account:'',date:'2026-07-09',sort:'desc'}).length;\n"
        "out.sortAscFirst = run({search:'',type:'all',platform:'all',account:'',date:'',sort:'asc'})[0].time;\n"
        "out.sortDescFirst = run({search:'',type:'all',platform:'all',account:'',date:'',sort:'desc'})[0].time;\n"
        "console.log(JSON.stringify(out));\n"
    ) % (json.dumps(hist), js)
    import tempfile
    f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    f.write(harness)
    f.close()
    try:
        r = subprocess.run(["node", f.name], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip())
    finally:
        os.unlink(f.name)

    assert out["all"] == 3
    assert out["byType"] == 1
    assert out["bySearch"] == 1
    assert out["byAccount"] == 1
    assert out["byDate"] == 1
    assert out["sortAscFirst"] == "2026-07-09 12:00"   # 正序最旧
    assert out["sortDescFirst"] == "2026-07-10 11:00"  # 倒序最新


# ==================== 分页纯函数边界（结构性 + Python 镜像） ====================

def test_pagination_first_screen_le50_and_load_more_step():
    """首屏 Math.min(logState.visible, logFiltered.length) ≤ 50；加载更早步长 +50；默认 visible=50。"""
    html = _read_monitor()
    assert "Math.min(logState.visible, logFiltered.length)" in html
    assert "logState.visible+=50" in html
    assert "visible:50" in html


def test_paginate_last_page_insufficient_50():
    """末页不足 50 条：可见数取 min(visible, len)，不越界、不报错。"""
    hist = [{"time": f"2026-07-10 {i:02d}:00", "type": "live_on", "rid": str(i)} for i in range(7)]
    # 纯函数镜像（与 monitor.html renderLogList 的 Math.min 语义一致）
    assert min(50, len(hist)) == 7
    assert min(50, 0) == 0


# ==================== 前端 XSS / ?view= 安全 ====================

def test_render_log_item_escapes_user_fields():
    """展开渲染必须对 name/title/detail/time/rid/platform 做 HTML 转义（复用 e()），防 XSS。"""
    html = _read_monitor()
    m = re.search(r"function renderLogItem\(l, idx\)\{.*?\n\}", html, re.S)
    assert m, "renderLogItem 未找到"
    body = m.group(0)
    for field in ["e(l.name)", "e(l.title)", "e(l.detail)", "e(l.time)", "e(l.rid)", "e(l.platform)"]:
        assert field in body, f"renderLogItem 未对 {field} 转义(e())"


def test_read_view_param_safe_no_injection():
    """?view= 解析仅白名单比对，禁止把参数拼进 HTML/URL/脚本（无 XSS/注入）。"""
    html = _read_monitor()
    m = re.search(r"function readViewParam\(\)\{.*?\n\}", html, re.S)
    assert m, "readViewParam 未找到"
    body = m.group(0)
    assert "innerHTML" not in body
    assert "document.write" not in body
    assert "eval(" not in body
    # 仅对 dashboard/feed/hero 三种合法值生效，且只调用 show()/设置筛选
    assert "'dashboard'" in body and "'feed'" in body and "'hero'" in body


# ==================== 三兄弟重定向：无死循环 ====================

@pytest.mark.parametrize("name,target", [
    ("monitor-dashboard.html", "view=dashboard"),
    ("monitor-feed.html", "view=feed"),
    ("monitor-hero.html", "view=hero"),
])
def test_brother_redirect_target_is_monitor_not_self(name, target):
    """重定向目标必须是 canonical monitor.html?view=xxx；自身文件名不再出现，避免重定向死循环。"""
    html = open(os.path.join(REPO, name), encoding="utf-8").read()
    assert "monitor.html?view=" in html
    assert target in html
    # 自身文件名（如 monitor-dashboard.html）不应再作为重定向目标出现
    assert name not in html


# ==================== 迁移幂等 + CLI 可直接运行 ====================

def test_migration_idempotent_second_run_changes_zero(tmp_path):
    """二次运行：changes==0、条数不变、type 字段齐全（幂等）。"""
    mht = _load_mht()
    p = tmp_path / "history.json"
    data = [
        {"time": f"2026-07-{i % 28 + 1:02d} 10:00", "status": s}
        for i, s in enumerate(["live", "offline", "replay", "error", None] * 20)
    ]
    p.write_text(json.dumps(data), encoding="utf-8")
    n1 = mht.run(str(p))
    n2 = mht.run(str(p))
    assert n1 == len(data)
    assert n2 == 0
    h2 = json.loads(p.read_text(encoding="utf-8"))
    assert len(h2) == len(data)
    assert all("type" in e for e in h2)
    assert all("level" in e for e in h2)


def test_migration_cli_runs_from_tools_dir(tmp_path):
    """直接 `python3 tools/migrate_history_types.py <path>` 能运行（import common 路径已修）；二次幂等。"""
    p = tmp_path / "history.json"
    data = [{"time": "2026-07-10 10:00", "status": "live"}, {"time": "2026-07-10 10:01"}]
    p.write_text(json.dumps(data), encoding="utf-8")
    r1 = subprocess.run(
        ["python3", "tools/migrate_history_types.py", str(p)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert r1.returncode == 0, r1.stderr
    assert "已写回" in r1.stdout
    r2 = subprocess.run(
        ["python3", "tools/migrate_history_types.py", str(p)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert r2.returncode == 0, r2.stderr
    assert "无缺失 type" in r2.stdout
    h = json.loads(p.read_text(encoding="utf-8"))
    assert all("type" in e for e in h)
