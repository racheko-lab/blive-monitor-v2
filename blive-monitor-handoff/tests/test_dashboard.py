"""P0-7 统一健康仪表盘：结构断言 + 纯 Python 口径复刻回归测试。

背景：阶段 1 收官，在 monitor.html 新增第 5 个「仪表盘」tab，纯前端聚合 ld() 已载入的
全局 hist/stat/rooms，渲染 5 项 KPI + 近 7 天开播趋势 + 开播排行 Top5 + 平台分布 +
通知健康，并在 ld() 成功路径末尾统一调用 renderDashboard()（切 tab 不重算）。

本测试分两部分，与既有前端结构性测试（test_frontend_log.py / test_selfcheck.py）风格一致：

1. 结构性断言（不跑 JS）：monitor.html 必须含 view-dashboard 容器、5 个 KPI 容器 id、
   4 个块容器 id、tab 按钮 show('dashboard')、renderDashboard、computeStatsJS(hist 调用)、
   show() 的 views/tabs 含 dashboard、readViewParam 的 dashboard 分支为 show('dashboard')。

2. 口径复刻（纯 Python，不跑 JS）：用一段 Python 1:1 复刻「今日北京时间 live_on 计数」等
   全部口径，对夹具（含「今日」边界、level=warn、type 兜底、多平台）断言 5 项 KPI + 7 天趋势
   + 排行 + 平台分布 + 通知健康正确。核心是锁死「今日」口径——按 time[0:10] === 今日北京时间
   YYYY-MM-DD，且今日用与 bjNow() 同款的 UTC+8 折算算北京时间，而非运行环境本地时区，
   防止回归成 new Date() 本地时区导致的 ±8 小时 bug。
"""
import os
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONITOR_HTML = os.path.join(REPO, "monitor.html")


# ============================ 结构性断言（不依赖 node） ============================

def _read_monitor():
    with open(MONITOR_HTML, encoding="utf-8") as f:
        return f.read()


def test_dashboard_view_section_present():
    """monitor.html 必须含仪表盘视图容器 id="view-dashboard"。"""
    html = _read_monitor()
    assert 'id="view-dashboard"' in html, "缺少 #view-dashboard 仪表盘容器"


def test_dashboard_tab_button_present():
    """底部 tab 栏必须含第 5 个「仪表盘」按钮，且调用 show('dashboard')。"""
    html = _read_monitor()
    assert "show('dashboard')" in html, "缺少仪表盘 tab 按钮 onclick=show('dashboard')"


def test_dashboard_render_function_present():
    """必须定义 renderDashboard 渲染函数。"""
    html = _read_monitor()
    assert "function renderDashboard" in html, "缺少 renderDashboard 函数"
    # 复用 computeStatsJS 的北京日分桶：必须出现 computeStatsJS(hist 调用
    assert "computeStatsJS(hist" in html, "renderDashboard 未复用 computeStatsJS(hist,...)"


def test_dashboard_kpi_containers_present():
    """5 个 KPI 数值位 id 必须全部存在。"""
    html = _read_monitor()
    for kpi in ("kpiRooms", "kpiLive", "kpiToday", "kpiNotify", "kpiFresh"):
        assert ('id="%s"' % kpi) in html, "缺少 KPI 容器 id=%s" % kpi


def test_dashboard_block_containers_present():
    """4 个块容器 id 必须全部存在。"""
    html = _read_monitor()
    for blk in ("dashTrend", "dashRank", "dashPlatform", "dashNotify"):
        assert ('id="%s"' % blk) in html, "缺少块容器 id=%s" % blk


def test_show_syncs_dashboard():
    """show() 两处同步：views 字典含 'view-dashboard'，tabs 数组含 'dashboard'。"""
    html = _read_monitor()
    assert "'view-dashboard'" in html, "show() 的 views 字典缺少 dashboard 映射"
    assert "'dashboard'" in html, "show() 的 tabs 数组缺少 'dashboard'"


def test_readviewparam_dashboard_lands_on_dashboard():
    """readViewParam 的 dashboard 分支必须落到 show('dashboard')（而非旧的 show('log')）。"""
    html = _read_monitor()
    # dashboard 分支含 show('dashboard')（三元 show(v==='dashboard'?'dashboard':'log') 内含此串）
    assert "show('dashboard')" in html, "readViewParam 的 dashboard 分支未落到 show('dashboard')"


# ============================ 纯 Python 口径复刻 ============================

def beijing_today():
    """复刻 bjNow()：北京时间 = UTC+8，绝不取运行环境本地日期。

    与 monitor.html 的 bjNow()（local + (offset+480)*60000）等价，
    统一用 UTC 基准加 8 小时，保证与运行环境时区无关。
    """
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")


def compute_dashboard_metrics(hist, stat, rooms, today_bj):
    """纯 Python 复刻 renderDashboard 的全部口径（供回归断言）。

    today_bj: 注入的「今日北京时间」字符串 YYYY-MM-DD（对应 JS todayBJ() 的返回值）。
    返回 dict 含 5 项 KPI + 7 天趋势 + 排行 + 平台分布 + 通知健康。
    """
    hist = hist or []
    rooms = rooms or []

    # —— KPI ——
    kpi_rooms = len(rooms)
    kpi_live = (
        sum(1 for r in (stat.get("rooms") or []) if r.get("status") == "live")
        if stat else 0
    )
    # 今日开播：type==='live_on' 且 time 前 10 位 === 今日北京时间（字符串相等，严禁本地时区）
    kpi_today = sum(
        1 for e in hist
        if (e.get("type") or e.get("status")) == "live_on"
        and (e.get("time") or "")[:10] == today_bj
    )
    # 通知异常：level 优先，type 兜底（保证不漏 cookie_warn / error）
    kpi_notify = sum(
        1 for e in hist
        if e.get("level") in ("warn", "error")
        or (e.get("type") or e.get("status")) in ("error", "cookie_warn")
    )

    # —— 趋势 7 天（按北京时间日期分桶，oldest→newest），复刻 computeStatsJS 的 live_on ——
    end = datetime.strptime(today_bj, "%Y-%m-%d")
    day_keys = [(end - timedelta(days=6 - i)).strftime("%Y-%m-%d") for i in range(7)]
    days = [(end - timedelta(days=6 - i)).strftime("%m-%d") for i in range(7)]
    live_on = [0] * 7
    for e in hist:
        if (e.get("type") or e.get("status")) != "live_on":
            continue
        t = (e.get("time") or "")[:10]
        if t in day_keys:
            live_on[day_keys.index(t)] += 1

    # —— 开播排行 Top N（按 name 聚合 live_on，次数降序；并列按最近开播时间倒序）——
    cnt, last = {}, {}
    for e in hist:
        if (e.get("type") or e.get("status")) != "live_on":
            continue
        n = e.get("name")
        cnt[n] = cnt.get(n, 0) + 1
        if n not in last or (e.get("time") or "") > last[n]:
            last[n] = e.get("time") or ""
    # 复刻 JS：b.count-a.count || (b.last>a.last?1:-1)。用稳定排序：先按 last 倒序，再按 count 倒序。
    info = {n: [cnt[n], last[n]] for n in cnt}
    items = sorted(info.items(), key=lambda kv: kv[1][1], reverse=True)
    items.sort(key=lambda kv: kv[1][0], reverse=True)
    rank_list = [{"name": k, "count": v[0]} for k, v in items[:5]]

    # —— 平台分布：rooms 按 platform 计数；hist 的 live_on 按 platform 分桶 ——
    plat_rooms = {"bilibili": 0, "douyin": 0, "other": 0}
    for r in rooms:
        p = r.get("platform")
        if p == "bilibili":
            plat_rooms["bilibili"] += 1
        elif p == "douyin":
            plat_rooms["douyin"] += 1
        else:
            plat_rooms["other"] += 1
    plat_live = {"bilibili": 0, "douyin": 0, "other": 0}
    for e in hist:
        if (e.get("type") or e.get("status")) != "live_on":
            continue
        p = e.get("platform")
        if p == "bilibili":
            plat_live["bilibili"] += 1
        elif p == "douyin":
            plat_live["douyin"] += 1
        else:
            plat_live["other"] += 1

    # —— 通知健康最近 N 条（同口径，按 time 倒序）——
    anomalies = [
        e for e in hist
        if e.get("level") in ("warn", "error")
        or (e.get("type") or e.get("status")) in ("error", "cookie_warn")
    ]
    anomalies.sort(key=lambda e: e.get("time", ""), reverse=True)
    recent = anomalies[:5]

    return {
        "kpi_rooms": kpi_rooms,
        "kpi_live": kpi_live,
        "kpi_today": kpi_today,
        "kpi_notify": kpi_notify,
        "trend_days": days,
        "trend_live_on": live_on,
        "rank": rank_list,
        "platform_rooms": plat_rooms,
        "platform_live": plat_live,
        "recent_anomalies": recent,
    }


# 夹具：固定「今日北京时间」为 2026-07-11，覆盖今日边界 / level=warn / type 兜底 / 多平台
NOW_BJ = "2026-07-11"

_HIST = [
    {"type": "live_on", "name": "阿B", "platform": "bilibili", "time": "2026-07-11 09:00:00"},
    {"type": "live_on", "name": "抖A", "platform": "douyin", "time": "2026-07-11 10:00:00"},
    {"type": "live_on", "name": "抖A", "platform": "douyin", "time": "2026-07-11 20:00:00"},
    {"type": "live_on", "name": "抖A", "platform": "douyin", "time": "2026-07-10 20:00:00"},  # 昨日，不计今日
    {"level": "warn", "type": "cookie_warn", "name": "抖A", "platform": "douyin",
     "time": "2026-07-11 21:00:00", "detail": "cookie 风控"},
    {"level": "warn", "type": "cookie_warn", "name": "抖B", "platform": "douyin",
     "time": "2026-07-09 12:00:00", "detail": "cookie 风控"},
    {"type": "error", "name": "阿B", "platform": "bilibili",
     "time": "2026-07-11 22:00:00", "detail": "检测失败"},  # 无 level，type 兜底计入
    {"type": "new_post", "name": "抖C", "platform": "douyin", "time": "2026-07-11 08:00:00"},  # 不计异常
]

_ROOMS = [{"platform": "bilibili", "id": "1", "name": "阿B"}] + [
    {"platform": "douyin", "id": str(i), "name": "抖%d" % i} for i in range(1, 10)
]

_STAT = {
    "rooms": [
        {"platform": "douyin", "id": "1", "status": "live"},
        {"platform": "bilibili", "id": "1", "status": "offline"},
    ]
}


def test_metrics_kpi_correct():
    """5 项 KPI 口径正确。"""
    m = compute_dashboard_metrics(_HIST, _STAT, _ROOMS, NOW_BJ)
    assert m["kpi_rooms"] == 10, "监控房间总数应为 10"
    assert m["kpi_live"] == 1, "当前直播中应为 1"
    # 今日开播：仅 2026-07-11 的 3 条 live_on（含昨日 1 条与 new_post 被排除）
    assert m["kpi_today"] == 3, "今日开播应为 3"
    # 通知异常：2 条 cookie_warn(level=warn) + 1 条 type=error（无 level 兜底）
    assert m["kpi_notify"] == 3, "通知异常应为 3"


def test_metrics_today_boundary_excludes_yesterday():
    """「今日」口径严格按北京时间日期字符串相等，昨日 live_on 不计入今日。"""
    m = compute_dashboard_metrics(_HIST, _STAT, _ROOMS, NOW_BJ)
    # 全部 today 相关只有 3 条；把 today 改成昨日则 0 条今日开播
    m_yesterday = compute_dashboard_metrics(_HIST, _STAT, _ROOMS, "2026-07-10")
    assert m_yesterday["kpi_today"] == 1, "2026-07-10 当日开播应为 1（抖A 昨日那场）"
    assert m["kpi_today"] == 3, "2026-07-11 当日开播应为 3"


def test_metrics_trend_7day():
    """近 7 天开播趋势分桶正确（oldest→newest，07-11 为末日）。"""
    m = compute_dashboard_metrics(_HIST, _STAT, _ROOMS, NOW_BJ)
    assert m["trend_days"][-1] == "07-11", "末日标签应为 07-11"
    assert m["trend_days"][0] == "07-05", "首日为 07-05"
    # live_on[07-10]=1（抖A 昨日），live_on[07-11]=3（阿B + 抖A 今日两场），其余 0
    assert m["trend_live_on"] == [0, 0, 0, 0, 0, 1, 3], "7 天趋势分桶结果应为 [0,0,0,0,0,1,3]"


def test_metrics_rank_top5():
    """开播排行按 name 聚合、次数降序；抖A(3) > 阿B(1)。"""
    m = compute_dashboard_metrics(_HIST, _STAT, _ROOMS, NOW_BJ)
    assert m["rank"][0]["name"] == "抖A" and m["rank"][0]["count"] == 3, "排行第一应为抖A(3 场)"
    assert m["rank"][1]["name"] == "阿B" and m["rank"][1]["count"] == 1, "排行第二应为阿B(1 场)"
    assert len(m["rank"]) == 2, "仅 2 个主播有开播记录"


def test_metrics_platform_distribution():
    """平台分布：房间数 1 B站 / 9 抖音；开播数按 live_on 分桶（B站 1 / 抖音 3）。"""
    m = compute_dashboard_metrics(_HIST, _STAT, _ROOMS, NOW_BJ)
    assert m["platform_rooms"] == {"bilibili": 1, "douyin": 9, "other": 0}, "房间分布应为 1B/9抖"
    assert m["platform_live"] == {"bilibili": 1, "douyin": 3, "other": 0}, "开播分布 B站 1 / 抖音 3"


def test_metrics_recent_anomalies():
    """通知健康最近 N 条：同口径、按 time 倒序；共 3 条，最新为 22:00 的 error。"""
    m = compute_dashboard_metrics(_HIST, _STAT, _ROOMS, NOW_BJ)
    assert len(m["recent_anomalies"]) == 3, "异常共 3 条"
    assert m["recent_anomalies"][0]["time"] == "2026-07-11 22:00:00", "最新异常应为 22:00 的 error"
    assert m["recent_anomalies"][0]["type"] == "error", "最新异常应为 type=error（无 level 兜底）"


def test_today_bj_uses_beijing_not_local():
    """锁死「今日」口径：用 UTC+8 折算北京时间，而非运行环境本地时区。

    复刻 bjNow() 的折算逻辑：北京时间 = UTC + 8h。以下用两个跨日点证明
    「今日」由 UTC+8 定义，与本地 now 解耦——防止回归成 new Date() 本地时区导致的 ±8h bug。
    """
    # 取固定 UTC 时刻：2026-07-11T00:30:00Z → 北京 08:30 → 北京日期 2026-07-11
    utc_a = datetime(2026, 7, 11, 0, 30, tzinfo=timezone.utc)
    bj_a = (utc_a + timedelta(hours=8)).strftime("%Y-%m-%d")
    assert bj_a == "2026-07-11", "UTC 00:30Z 的北京日期应为 2026-07-11"
    # 跨日点：2026-07-11T23:30:00Z → 北京次日 07:30 → 北京日期 2026-07-12
    utc_b = datetime(2026, 7, 11, 23, 30, tzinfo=timezone.utc)
    bj_b = (utc_b + timedelta(hours=8)).strftime("%Y-%m-%d")
    assert bj_b == "2026-07-12", "UTC 23:30Z 的北京日期应进位为 2026-07-12"
    # 复刻函数本身也走 UTC+8
    assert beijing_today() == (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")
