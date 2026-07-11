"""A1 定时摘要自动投递 — 回归测试。

覆盖：
  - compute_since / compute_summary 与 monitor.html JS 逐字节对齐（黄金值 + node 实跑对比）
  - should_deliver 四态 gate（disabled / too_early / already_sent / cooldown / deliver）
  - format_summary 文案
  - 集成：monkeypatch push_utils.dispatch_push，验证「应投」真实调用 + 状态回写
    （成功写 lastSent 并清冷却；失败写冷却不写 lastSent；无 push 配置 no-op）

文件隔离：集成测试统一 monkeypatch.chdir(tmp_path)，不触碰仓库真实文件。
node 实跑对比用例在 node 不可用时 skip。
"""
import calendar
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime

import pytest

import auto_summary
import push_utils

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONITOR_HTML = os.path.join(REPO, "monitor.html")


# ==================== node 实跑辅助 ====================

def _has_node() -> bool:
    try:
        return subprocess.run(["node", "--version"], capture_output=True).returncode == 0
    except Exception:
        return False


def _read_monitor() -> str:
    with open(MONITOR_HTML, encoding="utf-8") as f:
        return f.read()


def _extract_func(html: str, start_pattern: str) -> str:
    """从 monitor.html 抽取一个以 start_pattern（含开头的 '{'）为签名的 JS 函数源码。

    使用括号配平，鲁棒地截取到匹配的右花括号。
    """
    m = re.search(start_pattern, html)
    assert m, "未能从 monitor.html 定位 JS 函数: %s" % start_pattern
    i = m.end() - 1  # 指向首个 '{'
    depth = 0
    while i < len(html):
        c = html[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return html[m.start(): i + 1]
        i += 1
    raise AssertionError("JS 函数未闭合: %s" % start_pattern)


def _run_node(js: str, zone: str = "UTC"):
    env = dict(os.environ)
    env["TZ"] = zone
    f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    try:
        f.write(js)
    finally:
        f.close()
    try:
        r = subprocess.run(
            ["node", f.name], capture_output=True, text=True, env=env, timeout=30
        )
    finally:
        os.unlink(f.name)
    return r.returncode, r.stdout, r.stderr


# ==================== compute_since ====================

def test_compute_since_daily():
    now = datetime(2026, 7, 11, 15, 30)  # 北京时间
    since = auto_summary.compute_since("daily", now)
    # 今日北京午夜 = 2026-07-11 00:00 北京 = 2026-07-10 16:00 UTC
    expected = calendar.timegm((2026, 7, 11, 0, 0, 0, 0, 0, 0)) - 8 * 3600
    assert since == expected


def test_compute_since_weekly():
    # 2026-07-11 是周六 -> 本周一 = 2026-07-06
    now = datetime(2026, 7, 11, 10, 0)
    since = auto_summary.compute_since("weekly", now)
    expected = calendar.timegm((2026, 7, 6, 0, 0, 0, 0, 0, 0)) - 8 * 3600
    assert since == expected


@pytest.mark.skipif(not _has_node(), reason="node 不可用，跳过与 JS 实跑对比")
def test_compute_since_vs_js():
    html = _read_monitor()
    js_func = _extract_func(html, r"function computeSince\(freq, nowBJ\)\{")
    for freq in ("daily", "weekly"):
        now = datetime(2026, 7, 11, 15, 30)
        py_since = auto_summary.compute_since(freq, now)
        js = (
            js_func + "\n"
            + "var offset = new Date().getTimezoneOffset();\n"
            + "var nowBJ = new Date(2026, 6, 11, 15, 30, 0);\n"
            + "console.log(JSON.stringify({offset: offset, since: computeSince('%s', nowBJ)}));\n"
            % freq
        )
        rc, stdout, stderr = _run_node(js, "Asia/Shanghai")
        assert rc == 0, "node 执行 computeSince 失败:\n%s\n%s" % (stdout, stderr)
        out = json.loads(stdout.strip().splitlines()[-1])
        # 注入的 TZ 必须真正生效（Asia/Shanghai offset = -480），否则跳过避免误判
        if abs(out["offset"] - (-480)) > 1:
            pytest.skip("环境不支持 TZ=Asia/Shanghai，跳过 computeSince JS 对比")
        assert out["since"] == py_since, "compute_since(%s) JS/Python 不一致" % freq


# ==================== compute_summary ====================

def _sample_hist():
    return [
        {"time": "2026-07-11 09:00:00", "type": "live_on", "platform": "bilibili", "rid": "1", "name": "A"},
        {"time": "2026-07-11 12:00:00", "type": "live_on", "platform": "bilibili", "rid": "1", "name": "A"},  # 同一人两次
        {"time": "2026-07-11 13:00:00", "type": "live_on", "platform": "douyin", "rid": "2", "name": "B"},
        {"time": "2026-07-11 14:00:00", "type": "new_post", "platform": "douyin", "rid": "2", "name": "B"},
        {"time": "2026-07-10 23:00:00", "type": "live_on", "platform": "bilibili", "rid": "3", "name": "C"},  # 昨日->不计
        {"time": "2026-07-11 15:00:00", "type": "system", "platform": "douyin", "rid": "9", "name": "X"},     # 非统计类型
    ]


def test_compute_summary():
    now = datetime(2026, 7, 11, 20, 0)
    since = auto_summary.compute_since("daily", now)
    res = auto_summary.compute_summary(_sample_hist(), since)
    assert res["liveOnCount"] == 2          # A 与 B 两个人开播
    assert res["newPostCount"] == 1          # 仅 1 条新作
    byname = {r["name"]: r for r in res["byRoom"]}
    assert byname["A"]["liveOn"] == 2        # A 当天开播 2 次（按事件计数）
    assert byname["B"]["newPost"] == 1
    assert res["rangeText"] == "2026-07-11"


def test_compute_summary_legacy_status():
    """兼容旧字段 status（前端 type||status 兼容）。"""
    now = datetime(2026, 7, 11, 20, 0)
    since = auto_summary.compute_since("daily", now)
    hist = [
        {"time": "2026-07-11 09:00:00", "status": "live_on", "platform": "bilibili", "rid": "1", "name": "A"},
    ]
    res = auto_summary.compute_summary(hist, since)
    assert res["liveOnCount"] == 1


@pytest.mark.skipif(not _has_node(), reason="node 不可用，跳过与 JS 实跑对比")
def test_compute_summary_vs_js():
    html = _read_monitor()
    js_parse = _extract_func(html, r"function parseBeijing\(s\)\{")
    js_pad = _extract_func(html, r"function pad2\(n\)\{")
    js_summary = _extract_func(html, r"function computeSummary\(hist, since\)\{")
    hist = _sample_hist()
    now = datetime(2026, 7, 11, 20, 0)
    since = auto_summary.compute_since("daily", now)
    js = (
        js_parse + "\n" + js_pad + "\n" + js_summary + "\n"
        + "var hist = %s;\n" % json.dumps(hist, ensure_ascii=False)
        + "var res = computeSummary(hist, %d);\n" % since
        + "console.log(JSON.stringify(res));\n"
    )
    rc, stdout, stderr = _run_node(js, "UTC")
    assert rc == 0, "node 执行 computeSummary 失败:\n%s\n%s" % (stdout, stderr)
    js_out = json.loads(stdout.strip().splitlines()[-1])
    py_out = auto_summary.compute_summary(hist, since)
    assert js_out["liveOnCount"] == py_out["liveOnCount"]
    assert js_out["newPostCount"] == py_out["newPostCount"]
    assert js_out["rangeText"] == py_out["rangeText"]
    js_rooms = sorted(js_out["byRoom"], key=lambda r: r["id"])
    py_rooms = sorted(py_out["byRoom"], key=lambda r: r["id"])
    assert len(js_rooms) == len(py_rooms)
    for jr, pr in zip(js_rooms, py_rooms):
        assert (jr["id"], jr["liveOn"], jr["newPost"]) == (pr["id"], pr["liveOn"], pr["newPost"])


# ==================== parse_beijing 对齐（canonical，源自 common） ====================

def test_parse_beijing_basic():
    # 2026-07-11 09:00:00 北京 = 2026-07-11 01:00:00 UTC
    expected = calendar.timegm((2026, 7, 11, 1, 0, 0, 0, 0, 0))
    assert auto_summary.parse_beijing("2026-07-11 09:00:00") == expected
    assert auto_summary.parse_beijing("2026-07-11T09:00:00") == expected  # T 分隔等价
    assert auto_summary.parse_beijing("") is None
    assert auto_summary.parse_beijing(None) is None
    assert auto_summary.parse_beijing("2026/07/11 09:00:00") is None  # 非法格式


# ==================== format_summary ====================

def test_format_summary():
    summary = {
        "liveOnCount": 2,
        "newPostCount": 1,
        "rangeText": "2026-07-11",
        "byRoom": [
            {"name": "A", "id": "1", "liveOn": 2, "newPost": 0},
            {"name": "B", "id": "2", "liveOn": 0, "newPost": 1},
        ],
    }
    title, desp = auto_summary.format_summary(summary, "daily", "2026-07-11")
    assert title == "今日摘要（2026-07-11）"
    assert "2 人开播 · 1 条新作" in desp
    assert "- A：开播2 次 / 新作0 条" in desp
    assert "- B：开播0 次 / 新作1 条" in desp
    # weekly 用「本周」
    title2, _ = auto_summary.format_summary(summary, "weekly", "2026-07-06")
    assert title2 == "本周摘要（2026-07-06）"
    # 空摘要（0 开播 0 新作）仍产出文案
    empty = {"liveOnCount": 0, "newPostCount": 0, "rangeText": "2026-07-11", "byRoom": []}
    t3, d3 = auto_summary.format_summary(empty, "daily", "2026-07-11")
    assert "0 人开播 · 0 条新作" in d3


# ==================== should_deliver 四态 gate ====================

def test_gate_disabled():
    ok, reason = auto_summary.should_deliver({"enabled": False}, datetime(2026, 7, 11, 12, 0), {})
    assert ok is False and reason == "disabled"
    # enabled 缺失 / 非 True 也视为 disabled
    ok2, r2 = auto_summary.should_deliver({}, datetime(2026, 7, 11, 12, 0), {})
    assert ok2 is False and r2 == "disabled"


def test_gate_too_early():
    cfg = {"enabled": True, "freq": "daily", "sendTime": "20:00"}
    now = datetime(2026, 7, 11, 12, 0)  # 早于当日 20:00
    ok, reason = auto_summary.should_deliver(cfg, now, {})
    assert ok is False and reason == "too_early"


def test_gate_already_sent():
    cfg = {"enabled": True, "freq": "daily", "sendTime": "00:00"}
    now = datetime(2026, 7, 11, 20, 0)
    since = auto_summary.compute_since("daily", now)
    state = {"lastSent": since + 100}  # 本周期已投
    ok, reason = auto_summary.should_deliver(cfg, now, state)
    assert ok is False and reason == "already_sent"


def test_gate_deliver():
    cfg = {"enabled": True, "freq": "daily", "sendTime": "00:00"}
    now = datetime(2026, 7, 11, 20, 0)
    state = {"lastSent": 0}
    ok, reason = auto_summary.should_deliver(cfg, now, state)
    assert ok is True and reason == "deliver"


def test_gate_cooldown():
    cfg = {"enabled": True, "freq": "daily", "sendTime": "00:00"}
    now = datetime(2026, 7, 11, 20, 0)
    since = auto_summary.compute_since("daily", now)

    # 同周期失败冷却内 -> cooldown
    state_cool = {"lastSent": 0, "lastFailedAt": int(time.time()), "lastFailedSince": since}
    ok, reason = auto_summary.should_deliver(cfg, now, state_cool)
    assert ok is False and reason == "cooldown"

    # 跨周期（lastFailedSince != since）-> 不冷却，立即允许
    state_cross = {"lastSent": 0, "lastFailedAt": int(time.time()), "lastFailedSince": since - 99999}
    ok2, reason2 = auto_summary.should_deliver(cfg, now, state_cross)
    assert ok2 is True and reason2 == "deliver"

    # 冷却已过期（远超 COOLDOWN）-> 不冷却
    state_exp = {"lastSent": 0, "lastFailedAt": int(time.time()) - 10 * 3600, "lastFailedSince": since}
    ok3, reason3 = auto_summary.should_deliver(cfg, now, state_exp)
    assert ok3 is True and reason3 == "deliver"


# ==================== 集成：main() 真实运行 ====================

def _write_integration_files(tmp_path, hist, state):
    (tmp_path / "history.json").write_text(
        json.dumps(hist, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "summary_state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )


def _fixed_now():
    return datetime(2026, 7, 11, 20, 0)


class _FakeResult:
    ok = True
    attempts = 1
    last_error = ""
    status_code = None


def test_integration_deliver_writes_state(tmp_path, monkeypatch):
    """应投：dispatch_push 被调用一次，summary_state.json 写入 lastSent 并清除冷却字段。"""
    monkeypatch.chdir(tmp_path)
    _write_integration_files(
        tmp_path,
        [
            {"time": "2026-07-11 09:00:00", "type": "live_on", "platform": "bilibili", "rid": "1", "name": "A"},
            {"time": "2026-07-11 13:00:00", "type": "new_post", "platform": "douyin", "rid": "2", "name": "B"},
        ],
        {"enabled": True, "freq": "daily", "sendTime": "09:00", "lastSent": 0},
    )
    monkeypatch.setenv(
        "BLIVE_CONFIG",
        json.dumps({
            "summary": {"enabled": True, "freq": "daily", "sendTime": "00:00"},
            "push": {"type": "wecom", "webhook": "http://example.com/x"},
        }),
    )
    monkeypatch.setattr(auto_summary, "bjnow", lambda: _fixed_now())

    calls = []
    res = _FakeResult()

    def _fake(push_cfg, title, desp):
        calls.append((title, desp, push_cfg))
        return res

    monkeypatch.setattr(push_utils, "dispatch_push", _fake)

    with pytest.raises(SystemExit) as e:
        auto_summary.main()
    assert e.value.code == 0
    assert len(calls) == 1
    title, desp, pcfg = calls[0]
    assert title == "今日摘要（2026-07-11）"
    assert "2 人开播 · 1 条新作" in desp
    assert pcfg.get("type") == "wecom"

    state = json.loads((tmp_path / "summary_state.json").read_text(encoding="utf-8"))
    assert state["lastSent"] > 0
    assert "lastFailedAt" not in state       # 成功清除冷却
    assert state["enabled"] is True          # 前端字段被保留
    assert state["freq"] == "daily"
    assert state["sendTime"] == "00:00"


def test_integration_fail_no_lastSent(tmp_path, monkeypatch):
    """投递失败：写 lastFailedAt/lastFailedSince 冷却字段，绝不写 lastSent。"""
    monkeypatch.chdir(tmp_path)
    _write_integration_files(
        tmp_path,
        [{"time": "2026-07-11 09:00:00", "type": "live_on", "platform": "bilibili", "rid": "1", "name": "A"}],
        {"enabled": True, "freq": "daily", "sendTime": "09:00", "lastSent": 0},
    )
    monkeypatch.setenv(
        "BLIVE_CONFIG",
        json.dumps({
            "summary": {"enabled": True, "freq": "daily", "sendTime": "00:00"},
            "push": {"type": "wecom", "webhook": "http://example.com/x"},
        }),
    )
    monkeypatch.setattr(auto_summary, "bjnow", lambda: _fixed_now())

    calls = []

    class _FailResult:
        ok = False
        attempts = 1
        last_error = "biz_reject: test"
        status_code = None

    def _fake(push_cfg, title, desp):
        calls.append((title, desp))
        return _FailResult()

    monkeypatch.setattr(push_utils, "dispatch_push", _fake)

    with pytest.raises(SystemExit) as e:
        auto_summary.main()
    assert e.value.code == 0
    assert len(calls) == 1

    state = json.loads((tmp_path / "summary_state.json").read_text(encoding="utf-8"))
    assert state["lastSent"] == 0           # 未写 lastSent
    assert "lastFailedAt" in state          # 写冷却
    assert "lastFailedSince" in state


def test_integration_no_push_noop(tmp_path, monkeypatch):
    """无有效 push 段：视为 no-op，不调用推送、不写 lastSent、不写冷却。"""
    monkeypatch.chdir(tmp_path)
    _write_integration_files(
        tmp_path,
        [{"time": "2026-07-11 09:00:00", "type": "live_on", "platform": "bilibili", "rid": "1", "name": "A"}],
        {"enabled": True, "freq": "daily", "sendTime": "09:00", "lastSent": 0},
    )
    # 无 push 段
    monkeypatch.setenv(
        "BLIVE_CONFIG",
        json.dumps({"summary": {"enabled": True, "freq": "daily", "sendTime": "00:00"}}),
    )
    monkeypatch.setattr(auto_summary, "bjnow", lambda: _fixed_now())

    calls = []

    def _fake(push_cfg, title, desp):
        calls.append((title, desp))
        return None

    monkeypatch.setattr(push_utils, "dispatch_push", _fake)

    with pytest.raises(SystemExit) as e:
        auto_summary.main()
    assert e.value.code == 0
    assert len(calls) == 0                  # 未调用推送

    state = json.loads((tmp_path / "summary_state.json").read_text(encoding="utf-8"))
    assert state["lastSent"] == 0
    assert "lastFailedAt" not in state       # no-op 不写冷却


# ==================== Bug-A1-1 回归：成功路径必须清除磁盘上的失败冷却字段 ====================

def test_integration_success_clears_cooldown_fields(tmp_path, monkeypatch):
    """QA 场景回归（Bug-A1-1）：种子含上轮失败写入的 lastFailedAt/lastFailedSince。

    save_summary_state 会重读盘合并，若仅在内存 pop 会被磁盘合并打败 -> 落盘残留。
    修复后应通过 remove 参数在写回时显式删除这两个键。
    """
    monkeypatch.chdir(tmp_path)
    _write_integration_files(
        tmp_path,
        [
            {"time": "2026-07-11 09:00:00", "type": "live_on", "platform": "bilibili", "rid": "1", "name": "A"},
            {"time": "2026-07-11 13:00:00", "type": "new_post", "platform": "douyin", "rid": "2", "name": "B"},
        ],
        # 模拟上轮失败冷却字段仍残留在磁盘
        {"lastFailedAt": 111, "lastFailedSince": 222, "lastSent": 0},
    )
    monkeypatch.setenv(
        "BLIVE_CONFIG",
        json.dumps({
            "summary": {"enabled": True, "freq": "daily", "sendTime": "00:00"},
            "push": {"type": "wecom", "webhook": "http://example.com/x"},
        }),
    )
    monkeypatch.setattr(auto_summary, "bjnow", lambda: _fixed_now())

    calls = []
    res = _FakeResult()

    def _fake(push_cfg, title, desp):
        calls.append((title, desp))
        return res

    monkeypatch.setattr(push_utils, "dispatch_push", _fake)

    with pytest.raises(SystemExit) as e:
        auto_summary.main()
    assert e.value.code == 0
    assert len(calls) == 1

    state = json.loads((tmp_path / "summary_state.json").read_text(encoding="utf-8"))
    assert state["lastSent"] > 0                 # 成功写 lastSent
    assert "lastFailedAt" not in state           # 关键回归点：冷却字段被清除
    assert "lastFailedSince" not in state


def test_integration_failure_preserves_cooldown_fields(tmp_path, monkeypatch):
    """失败分支回归：种子同上，dispatch 返回失败 -> 落盘含冷却字段且无 lastSent。

    原行为不变（失败分支未改动）。
    """
    monkeypatch.chdir(tmp_path)
    _write_integration_files(
        tmp_path,
        [{"time": "2026-07-11 09:00:00", "type": "live_on", "platform": "bilibili", "rid": "1", "name": "A"}],
        {"lastFailedAt": 111, "lastFailedSince": 222, "lastSent": 0},
    )
    monkeypatch.setenv(
        "BLIVE_CONFIG",
        json.dumps({
            "summary": {"enabled": True, "freq": "daily", "sendTime": "00:00"},
            "push": {"type": "wecom", "webhook": "http://example.com/x"},
        }),
    )
    monkeypatch.setattr(auto_summary, "bjnow", lambda: _fixed_now())

    calls = []

    class _FailResult:
        ok = False
        attempts = 1
        last_error = "biz_reject: test"
        status_code = None

    def _fake(push_cfg, title, desp):
        calls.append((title, desp))
        return _FailResult()

    monkeypatch.setattr(push_utils, "dispatch_push", _fake)

    with pytest.raises(SystemExit) as e:
        auto_summary.main()
    assert e.value.code == 0
    assert len(calls) == 1

    state = json.loads((tmp_path / "summary_state.json").read_text(encoding="utf-8"))
    assert "lastSent" not in state or state.get("lastSent") == 0  # 失败不写 lastSent
    assert state["lastFailedAt"] > 0             # 写冷却
    assert "lastFailedSince" in state


# ==================== parse_beijing 畸形串归一为 None ====================

def test_parse_beijing_malformed_returns_none():
    """越界/畸形但正则放过的串 + 完全非法串 -> 一律 None，绝不抛异常。

    注意：calendar.timegm 与 JS Date 一样会「归一化」越界输入（如 2 月 30 日、
    25 时、61 分都会进位成一个合法日期而非报错），因此只有真正触发 ValueError/
    OverflowError 的串（如年/月/日/时严重越界）或正则不匹配的串才返回 None。
    """
    assert auto_summary.parse_beijing("2026-13-40 99:99:99") is None  # 严重越界 -> 抛错归一
    assert auto_summary.parse_beijing("2026-13-40T99:99:99") is None  # T 分隔同样越界
    assert auto_summary.parse_beijing("not-a-date") is None            # 正则不匹配
    assert auto_summary.parse_beijing("2026/07/11 09:00:00") is None  # 非法格式
    # 归一化输入仍应返回数字（与 JS Date 行为一致，不抛）
    assert auto_summary.parse_beijing("2026-02-30 25:61:99") is not None
