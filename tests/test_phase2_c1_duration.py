"""阶段二 2c C1 · 开播时长统计：Python 参考实现 + grep 契约。

前置结论（已验证）：history.json 当前样本无 live_on（仅 live_off/new_post），
故单测自建含成对 live_on/live_off 的夹具；参考实现与 monitor.html 的
computeLiveDuration / computeLiveDurationAll / renderDurationCard 逻辑对齐。

口径（前端↔Python 一致，时长单位统一为「秒」）：
  - 按房间 key('platform|rid') 配对 live_on/live_off；live_on 入栈，遇 live_off 出栈成 session；
  - 栈底未配对 live_on => 进行中（endSec=now，ongoing=true）；
  - totalSec=累计（含进行中，秒）；avgSec=已完成场次均值（进行中不计入）；
  - last30Sec=起始落在 [now-30d, now] 的 session 累计（秒）；ongoing 计入累计与近30天。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")


def _src():
    return open(HTML, encoding="utf-8").read()


# ---------------------------------------------------------------------------
# grep 契约
# ---------------------------------------------------------------------------
def test_c1_grep_contracts():
    src = _src()
    for token in ["function computeLiveDuration",
                  "function computeLiveDurationAll",
                  "function renderDurationCard",
                  "kpiDuration"]:
        assert token in src, "monitor.html 缺少 C1 契约标记: %s" % token


# ---------------------------------------------------------------------------
# Python 参考实现（镜像 JS 逻辑；以 epoch ms 工作，time 串仅用于稳定排序）
# ---------------------------------------------------------------------------
def _ev(platform, rid, typ, ms, time_str=None):
    if time_str is None:
        time_str = "%020d" % ms  # 零填充 => 字典序 == 数值序
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
            if on is not None:
                end = ev["_ms"]
                if end >= on["start"]:
                    sessions.append({"start": on["start"], "end": end, "ongoing": False})
    ongoing = False
    for s0 in stack:
        if s0["start"] is not None:
            sessions.append({"start": s0["start"], "end": now_ms, "ongoing": True})
            ongoing = True
    total = comp = cnt = l30 = 0
    last30ms = last30_days * 86400000
    for s in sessions:
        d = round((s["end"] - s["start"]) / 1000)  # 秒
        total += d
        if s["ongoing"]:
            pass
        else:
            comp += d
            cnt += 1
        if now_ms - s["start"] <= last30ms:
            l30 += d
    return {
        "totalSec": total,
        "avgSec": round(comp / cnt) if cnt else 0,
        "last30Sec": l30,
        "completedSec": comp,
        "completedCount": cnt,
        "sessionCount": len(sessions),
        "ongoing": ongoing,
    }


def compute_live_duration_all(hist, now_ms):
    keys = {}
    for e in (hist or []):
        if e.get("type") in ("live_on", "live_off"):
            keys[kb_key(e)] = True
    total = l30 = comp = cnt = sess = 0
    ongoing = False
    for key in keys:
        d = compute_live_duration(hist, key, now_ms)
        total += d["totalSec"]
        l30 += d["last30Sec"]
        comp += d["completedSec"]
        cnt += d["completedCount"]
        sess += d["sessionCount"]
        if d["ongoing"]:
            ongoing = True
    return {
        "totalSec": total,
        "avgSec": round(comp / cnt) if cnt else 0,
        "last30Sec": l30,
        "sessionCount": sess,
        "ongoing": ongoing,
    }


# 远未来参考时刻（用于相对偏移夹具，避免跨时区歧义）
FAR_NOW = 10_000_000_000


def test_duration_paired_sessions():
    hist = [
        _ev("bilibili", "1", "live_on", 1_000_000),
        _ev("bilibili", "1", "live_off", 1_000_000 + 3_600_000),   # 1h
        _ev("bilibili", "1", "live_on", 5_000_000),
        _ev("bilibili", "1", "live_off", 5_000_000 + 7_200_000),   # 2h
    ]
    now = 12_200_000 + 86_400_000  # 晚于最后事件 1 天，确保落在近30天
    d = compute_live_duration(hist, "bilibili|1", now)
    assert d["totalSec"] == 10_800, d               # 3h
    assert d["avgSec"] == 5_400, d                  # (1h+2h)/2
    assert d["last30Sec"] == 10_800, d              # 两场都在近30天
    assert d["sessionCount"] == 2
    assert d["ongoing"] is False


def test_duration_ongoing_not_in_avg():
    hist = [
        _ev("douyin", "9", "live_on", FAR_NOW - 1_800_000),  # 30 分钟前开播，未下播
    ]
    d = compute_live_duration(hist, "douyin|9", FAR_NOW)
    assert d["ongoing"] is True
    assert d["totalSec"] == 1_800, d                 # 累计含进行中（秒）
    assert d["avgSec"] == 0, d                       # 进行中不计入均值
    assert d["last30Sec"] == 1_800, d                # 近30天含进行中
    assert d["sessionCount"] == 1


def test_duration_last30_boundary():
    # 40 天前开播、39 天前下播（1h），不应计入近30天
    on = FAR_NOW - 40 * 86400000
    hist = [
        _ev("bilibili", "1", "live_on", on),
        _ev("bilibili", "1", "live_off", on + 3_600_000),
    ]
    d = compute_live_duration(hist, "bilibili|1", FAR_NOW)
    assert d["totalSec"] == 3_600, d                 # 累计含（秒）
    assert d["last30Sec"] == 0, d                    # 近30天不含（起始 >30 天前）
    assert d["avgSec"] == 3_600, d


def test_duration_all_aggregates():
    now = 12_200_000 + 86_400_000  # 98_600_000
    hist = [
        # 房间 A：两场已完成（1h+2h）
        _ev("bilibili", "1", "live_on", 1_000_000),
        _ev("bilibili", "1", "live_off", 1_000_000 + 3_600_000),
        _ev("bilibili", "1", "live_on", 5_000_000),
        _ev("bilibili", "1", "live_off", 5_000_000 + 7_200_000),
        # 房间 B：进行中 30 分钟（锚定到同一 now）
        _ev("douyin", "9", "live_on", now - 1_800_000),
    ]
    d = compute_live_duration_all(hist, now)
    assert d["totalSec"] == 10_800 + 1_800, d
    assert d["avgSec"] == 5_400, d                   # 仅 A 的两场算均值
    assert d["last30Sec"] == 10_800 + 1_800, d
    assert d["ongoing"] is True
    assert d["sessionCount"] == 3


def test_duration_empty_hist():
    d = compute_live_duration([], "bilibili|1", FAR_NOW)
    assert d["totalSec"] == 0 and d["avgSec"] == 0 and d["sessionCount"] == 0
    assert d["ongoing"] is False
