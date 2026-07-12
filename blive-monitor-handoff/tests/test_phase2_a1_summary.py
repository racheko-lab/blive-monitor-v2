"""阶段二 2a · A1 定时摘要：纯函数参考实现 + grep 契约。

本文件提供与 monitor.html 中 JS 纯函数（computeSince / computeSummary）逻辑一致的
Python 参考实现，并用夹具验证其正确性；同时 grep monitor.html 确认前端契约标记
（函数名 / 控件 id）存在，满足 PRD §附录「新增契约」保护清单。
"""
import os
import re
import calendar
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")


# ---------------------------------------------------------------------------
# grep 契约：monitor.html 必须包含以下标记（函数名 / 控件 id）
# ---------------------------------------------------------------------------
def test_monitor_html_has_a1_summary_contract():
    src = open(HTML, encoding="utf-8").read()
    for token in [
        "summaryEnabled", "summaryFreq", "summarySendTime",
        "computeSummary", "computeSince", "buildSummaryConfig",
        "summaryCard", "copySummary", "requestPushSummary",
        "maybeShowSummary", "renderSummary",
    ]:
        assert token in src, f"monitor.html 缺少 A1 契约标记: {token}"


# ---------------------------------------------------------------------------
# Python 参考实现（镜像 JS 逻辑，供参考测试；不依赖浏览器运行）
# ---------------------------------------------------------------------------
def _parse_beijing(s):
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$", s or "")
    if not m:
        return None
    y, mo, d, h, mi, se = map(int, m.groups())
    # 北京时间 → 真实 UTC 秒（与 JS parseBeijing 同一约定：减 8h）
    return calendar.timegm((y, mo, d, h, mi, se, 0, 0, 0)) - 8 * 3600


def computeSince(freq, now_bj):
    """镜像 JS computeSince：北京当日/本周一 00:00 的真实 UTC 秒。"""
    d = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    if freq == "weekly":
        d = d - timedelta(days=d.weekday())  # Monday=0..Sunday=6
    return calendar.timegm(d.timetuple()) - 8 * 3600


def computeSummary(hist, since):
    """镜像 JS computeSummary：按 type 计数 live_on（按房间）/ new_post。"""
    by_room = {}
    new_post_total = 0
    for ev in hist:
        t = ev.get("type") or ev.get("status")
        if t not in ("live_on", "new_post"):
            continue
        ts = _parse_beijing(ev.get("time"))
        if ts is None or ts < since:
            continue
        rid = str(ev.get("rid") or ev.get("account") or "")
        key = (ev.get("platform") or "") + "|" + rid
        room = by_room.get(key)
        if room is None:
            room = {
                "platform": ev.get("platform") or "",
                "id": rid,
                "name": ev.get("name") or "",
                "liveOn": 0,
                "newPost": 0,
            }
            by_room[key] = room
        if t == "live_on":
            room["liveOn"] += 1
        else:
            room["newPost"] += 1
            new_post_total += 1
    by_room_list = list(by_room.values())
    sd = datetime.utcfromtimestamp(since + 8 * 3600)
    rangeText = sd.strftime("%Y-%m-%d")
    return {
        "liveOnCount": len(by_room_list),
        "newPostCount": new_post_total,
        "byRoom": by_room_list,
        "rangeText": rangeText,
    }


# ---------------------------------------------------------------------------
# 参考实现断言
# ---------------------------------------------------------------------------
def test_computeSince_daily():
    now = datetime(2026, 7, 11, 15, 30)  # 北京时间
    since = computeSince("daily", now)
    # 今日北京午夜 = 2026-07-11 00:00 北京 = 2026-07-10 16:00 UTC
    expected = calendar.timegm((2026, 7, 11, 0, 0, 0, 0, 0, 0)) - 8 * 3600
    assert since == expected


def test_computeSince_weekly_monday():
    # 2026-07-11 是周六 → 本周一 = 2026-07-06
    now = datetime(2026, 7, 11, 10, 0)
    since = computeSince("weekly", now)
    expected = calendar.timegm((2026, 7, 6, 0, 0, 0, 0, 0, 0)) - 8 * 3600
    assert since == expected


def test_computeSummary_counts():
    now = datetime(2026, 7, 11, 20, 0)
    since = computeSince("daily", now)
    hist = [
        {"time": "2026-07-11 09:00:00", "type": "live_on", "platform": "bilibili", "rid": "1", "name": "A"},
        {"time": "2026-07-11 12:00:00", "type": "live_on", "platform": "bilibili", "rid": "1", "name": "A"},  # 同一人两次
        {"time": "2026-07-11 13:00:00", "type": "live_on", "platform": "douyin", "rid": "2", "name": "B"},
        {"time": "2026-07-11 14:00:00", "type": "new_post", "platform": "douyin", "rid": "2", "name": "B"},
        {"time": "2026-07-10 23:00:00", "type": "live_on", "platform": "bilibili", "rid": "3", "name": "C"},  # 昨日→不计
        {"time": "2026-07-11 15:00:00", "type": "system", "platform": "douyin", "rid": "9", "name": "X"},      # 非统计类型
    ]
    res = computeSummary(hist, since)
    assert res["liveOnCount"] == 2          # A 与 B 两个人开播
    assert res["newPostCount"] == 1          # 仅 1 条新作
    byname = {r["name"]: r for r in res["byRoom"]}
    assert byname["A"]["liveOn"] == 2        # A 当天开播 2 次（按事件计数）
    assert byname["B"]["newPost"] == 1
    assert res["rangeText"] == "2026-07-11"


def test_computeSummary_legacy_status_field():
    """兼容旧字段 status（前端 line 2190 的 type||status 兼容）。"""
    now = datetime(2026, 7, 11, 20, 0)
    since = computeSince("daily", now)
    hist = [
        {"time": "2026-07-11 09:00:00", "status": "live_on", "platform": "bilibili", "rid": "1", "name": "A"},
    ]
    res = computeSummary(hist, since)
    assert res["liveOnCount"] == 1
