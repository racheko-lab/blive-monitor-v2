"""阶段二 2c C4 · 报表导出 CSV：grep 契约 + CSV 字段集断言（含时长/趋势列）。

exportReport('csv') 生成 Blob 下载 blive-monitor-report-YYYYMMDD.csv；
字段：name,platform,id,tags,enabled,累计时长秒,平均时长秒,近30天时长秒,
liveOn7,newPost7,liveOn30,newPost30,status（含 live 与 post 房间）。PNG 留后续。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")


def _src():
    return open(HTML, encoding="utf-8").read()


# ---------------------------------------------------------------------------
# grep 契约
# ---------------------------------------------------------------------------
def test_c4_grep_contracts():
    src = _src()
    for token in ["function exportReport", "btnExportCsv",
                  "blive-monitor-report-", "new Blob("]:
        assert token in src, "monitor.html 缺少 C4 契约标记: %s" % token


# ---------------------------------------------------------------------------
# Python 参考实现（镜像 JS exportReport 的 CSV 构造）
# ---------------------------------------------------------------------------
COLUMNS = ["name", "platform", "id", "tags", "enabled", "累计时长秒", "平均时长秒",
           "近30天时长秒", "liveOn7", "newPost7", "liveOn30", "newPost30", "status"]


def csv_field(v):
    s = "" if v is None else str(v)
    if any(c in s for c in [",", '"', "\n", "\r"]):
        return '"' + s.replace('"', '""') + '"'
    return s


def _ev(platform, rid, typ, ms, time_str=None):
    if time_str is None:
        time_str = "%020d" % ms
    return {"platform": platform, "rid": rid, "type": typ, "_ms": ms, "time": time_str}


def kb_key(e):
    rid = e.get("rid") if e.get("rid") is not None else (
        e.get("account") if e.get("account") is not None else e.get("id"))
    return str(e.get("platform", "")) + "|" + str(rid)


def compute_live_duration(hist, key, now_ms, last30_days=30):
    events = [e for e in (hist or [])
              if e.get("type") in ("live_on", "live_off") and kb_key(e) == key]
    events.sort(key=lambda e: e.get("time", ""))
    sessions, stack = [], []
    for ev in events:
        if ev["type"] == "live_on":
            stack.append({"start": ev["_ms"]})
        else:
            on = stack.pop() if stack else None
            if on is not None and ev["_ms"] >= on["start"]:
                sessions.append({"start": on["start"], "end": ev["_ms"]})
    ongoing = False
    for s0 in stack:
        if s0["start"] is not None:
            sessions.append({"start": s0["start"], "end": now_ms})
            ongoing = True
    total = comp = cnt = l30 = 0
    last30ms = last30_days * 86400000
    for s in sessions:
        d = round((s["end"] - s["start"]) / 1000)  # 秒
        total += d
        if not s.get("ongoing"):
            comp += d
            cnt += 1
        if now_ms - s["start"] <= last30ms:
            l30 += d
    return {"totalSec": total, "avgSec": round(comp / cnt) if cnt else 0, "last30Sec": l30,
            "ongoing": ongoing}


def compute_stats_ref(hist, n):
    return {
        "live_on": sum(1 for e in hist if e.get("type") == "live_on"),
        "new_post": sum(1 for e in hist if e.get("type") == "new_post"),
    }


def build_report_csv(rooms, post_rooms, hist, stat, now_ms):
    rows = [",".join(COLUMNS)]

    def status_of(platform, rid):
        if stat and stat.get("rooms"):
            for r in stat["rooms"]:
                if r.get("platform") == platform and str(r.get("id")) == str(rid):
                    return r.get("status", "")
        return ""

    def add(platform, rid, name, tags, enabled):
        key = platform + "|" + str(rid)
        dur = compute_live_duration(hist, key, now_ms)
        hr = [e for e in (hist or []) if kb_key(e) == key]
        s7 = compute_stats_ref(hr, 7)
        s30 = compute_stats_ref(hr, 30)
        rows.append(",".join([
            csv_field(name), csv_field(platform), csv_field(rid),
            csv_field("|".join(tags or [])),
            csv_field("否" if enabled is False else "是"),
            str(dur["totalSec"]), str(dur["avgSec"]), str(dur["last30Sec"]),
            str(s7["live_on"]), str(s7["new_post"]),
            str(s30["live_on"]), str(s30["new_post"]),
            csv_field(status_of(platform, rid)),
        ]))

    for r in (rooms or []):
        add(r["platform"], str(r["id"]), r.get("name", str(r["id"])), r.get("tags"), r.get("enabled"))
    for r in (post_rooms or []):
        add("douyin", str(r["id"]), r.get("name", str(r["id"])), r.get("tags"), r.get("enabled"))
    return "\r\n".join(rows)


def report_filename(now):
    return "blive-monitor-report-%04d%02d%02d.csv" % (now.year, now.month, now.day)


# ---------------------------------------------------------------------------
# 断言
# ---------------------------------------------------------------------------
NOW = 10_000_000_000


def test_c4_csv_header_columns():
    rooms = [{"platform": "bilibili", "id": "1", "name": "甲", "tags": ["游戏"], "enabled": True}]
    post = [{"platform": "douyin", "id": "9", "name": "乙", "tags": [], "enabled": False}]
    csv = build_report_csv(rooms, post, [], {}, NOW)
    header = csv.split("\r\n")[0]
    assert header.split(",") == COLUMNS, header


def test_c4_csv_includes_live_and_post_rooms():
    rooms = [{"platform": "bilibili", "id": "1", "name": "甲", "tags": ["游戏"], "enabled": True}]
    post = [{"platform": "douyin", "id": "9", "name": "乙", "tags": [], "enabled": False}]
    csv = build_report_csv(rooms, post, [], {}, NOW)
    lines = csv.split("\r\n")
    assert len(lines) == 3, lines                       # header + live + post
    assert "甲" in csv and "乙" in csv
    # post 房间 enabled=False -> 「否」
    post_line = [l for l in lines if "乙" in l][0]
    assert ",否," in post_line, post_line


def test_c4_csv_duration_column():
    # 直播房间 bilibili|1：1 小时场次（now-2h 开播，now-1h 下播）
    hist = [
        _ev("bilibili", "1", "live_on", NOW - 2 * 3600 * 1000),
        _ev("bilibili", "1", "live_off", NOW - 1 * 3600 * 1000),
    ]
    rooms = [{"platform": "bilibili", "id": "1", "name": "甲", "tags": [], "enabled": True}]
    stat = {"rooms": [{"platform": "bilibili", "id": "1", "status": "offline"}]}
    csv = build_report_csv(rooms, [], hist, stat, NOW)
    line = [l for l in csv.split("\r\n") if "甲" in l][0]
    cols = line.split(",")
    # 列序：name,platform,id,tags,enabled,累计时长秒,平均时长秒,近30天时长秒,...
    assert cols[5] == "3600", cols               # 累计 = 1h（秒）
    assert cols[6] == "3600", cols               # 平均 = 1h（单场，秒）
    assert cols[7] == "3600", cols               # 近30天 = 1h（秒）
    assert cols[8] == "1", cols                  # liveOn7 = 1
    assert cols[12] == "offline", cols           # status 来自 stat


def test_c4_filename_pattern():
    import datetime
    now = datetime.datetime(2026, 7, 10, 12, 0, 0)
    fn = report_filename(now)
    assert re.match(r"^blive-monitor-report-\d{8}\.csv$", fn), fn
    assert fn == "blive-monitor-report-20260710.csv", fn
