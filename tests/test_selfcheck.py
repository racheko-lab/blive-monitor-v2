"""P0-1 监控自检心跳：parseBeijing / calcFreshness 回归测试。

背景：P0-1 在 monitor.html 内新增「监控自检」能力——复用 bjNow() 的时区折算思路，
把北京时间字符串 status.json.updated 解析为真实 UTC 毫秒，算出「新鲜度」四态
（ok ≤10 / warn 10–30 / stale >30 / loadfail 取不到），驱动常驻 #healthBar。

本测试沿用仓库既有 pytest + 真实 node 实跑 JS 的范式（参考 test_live_rooms_load.py）：

  - 结构性断言（不依赖 node）：monitor.html 必须含 #healthBar、FRESH_WARN_MIN、
    FRESH_STALE_MIN、parseBeijing、calcFreshness。
  - 功能性断言（node 实跑抽出的函数）：
      1) 无 8 小时 bug：parseBeijing 对同一天相邻 10 分钟的差 = 10*60*1000
         （注：该用例两个时间共享同一偏移项，符号写反也会自抵消成「假绿」，
          故必须配合下方跨时区用例才能真正卡住 bug）；
      2) calcFreshness 三态 + 空串：now-5→ok、now-20→warn、now-40→stale、''→loadfail；
      3) mins 数值正确（now-20 → mins===20）；
      4) 【跨时区不变量】parseBeijing("2026-07-10 21:30:52") 在 Asia/Shanghai / UTC /
         America/New_York / Europe/London 四个时区下，都必须 === Date.UTC(2026,6,10,13,30,52)
         （即北京时间 21:30:52 对应的真实 UTC 毫秒）。此用例用 subprocess 分别以不同 TZ
         环境变量启动 node，无论 CI/浏览器处于哪个时区，符号写错都会被抓出。

node 不可用时整体 skip（不报错）。
"""
import json
import os
import re
import subprocess
import tempfile

import pytest

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


def _extract_selfcheck_js(html: str) -> str:
    """抽取 P0-1 代码段：从 `var FRESH_WARN_MIN` 到 `function computeStatsJS` 前。

    该区间包含阈值常量 + parseBeijing + calcFreshness，且全文件仅此一处同时满足
    「FRESH_WARN_MIN 定义」+「紧邻 computeStatsJS」的边界，可唯一定位。
    """
    pat = r"var FRESH_WARN_MIN.*?\nfunction computeStatsJS"
    m = re.search(pat, html, re.S)
    assert m, "未能从 monitor.html 定位 P0-1 自检代码段（FRESH_WARN_MIN … computeStatsJS）"
    return m.group(0).replace("\nfunction computeStatsJS", "")


def _run_node_with_tz(js: str, zone: str):
    """以指定 TZ 环境变量启动 node 子进程执行 js，返回 (returncode, stdout, stderr, env)。

    通过 env={'TZ': zone, **os.environ} 注入时区；node 读取 process.env.TZ 决定
    Date 的本地时区解释。返回 env 供调用方确认本次子进程实际生效的时区。
    """
    env = dict(os.environ)
    env["TZ"] = zone
    f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    try:
        f.write(js)
    finally:
        f.close()
    try:
        r = subprocess.run(
            ["node", f.name], capture_output=True, text=True, env=env
        )
    finally:
        os.unlink(f.name)
    return r.returncode, r.stdout, r.stderr


# ==================== 结构性断言（不依赖 node） ====================

def test_health_bar_id_present():
    """monitor.html 必须含有常驻健康条 #healthBar。"""
    html = _read_monitor()
    assert 'id="healthBar"' in html, "monitor.html 缺少 #healthBar 元素"
    assert "healthBar" in html


def test_selfcheck_symbols_present():
    """阈值常量与两个核心函数必须存在，供健康条渲染与测试复用。"""
    html = _read_monitor()
    assert "FRESH_WARN_MIN" in html, "缺少阈值常量 FRESH_WARN_MIN"
    assert "FRESH_STALE_MIN" in html, "缺少阈值常量 FRESH_STALE_MIN"
    assert "parseBeijing" in html, "缺少 parseBeijing"
    assert "calcFreshness" in html, "缺少 calcFreshness"


def test_selfcheck_js_extractable():
    """P0-1 代码段可被稳定抽取（保证 node 实跑分支不会因定位失败而漏测）。"""
    html = _read_monitor()
    frag = _extract_selfcheck_js(html)
    assert "function parseBeijing" in frag, "抽出的代码段缺少 parseBeijing"
    assert "function calcFreshness" in frag, "抽出的代码段缺少 calcFreshness"
    assert "var FRESH_WARN_MIN" in frag, "抽出的代码段缺少 FRESH_WARN_MIN"


# ==================== 功能性断言（node 实跑） ====================

@pytest.mark.skipif(not _has_node(), reason="node 不可用，跳过前端自检函数实跑校验")
def test_parse_beijing_no_eight_hour_bug():
    """无 8 小时 bug：同日相邻 10 分钟的两个北京时间，解析后差恰为 10*60*1000。

    证明折算与运行环境时区无关（bjNow 同款 offset 折算生效）。
    """
    html = _read_monitor()
    frag = _extract_selfcheck_js(html)
    js = (
        "var stat = null;\n"
        + frag + "\n"
        + "var d1 = parseBeijing('2026-07-10 21:30:52');\n"
        + "var d0 = parseBeijing('2026-07-10 21:20:52');\n"
        + "console.log(JSON.stringify({"
        + "  diff: d1 - d0,"
        + "  expect: 10*60*1000,"
        + "  ok: (d1 - d0) === 10*60*1000"
        + "}));\n"
    )
    f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    try:
        f.write(js)
    finally:
        f.close()
    try:
        r = subprocess.run(["node", f.name], capture_output=True, text=True)
    finally:
        os.unlink(f.name)
    assert r.returncode == 0, "node 执行 parseBeijing 失败：\n%s\n%s" % (r.stdout, r.stderr)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["ok"] is True, (
        "parseBeijing 出现 8 小时 bug：相邻 10 分钟差应为 600000，实际 %s" % out["diff"]
    )


@pytest.mark.skipif(not _has_node(), reason="node 不可用，跳过前端自检函数实跑校验")
def test_calc_freshness_states_and_mins():
    """calcFreshness 三态 + 空串 + mins 数值：

      now-5  → ok    ；now-20 → warn（mins===20）；now-40 → stale；'' → loadfail。
    """
    html = _read_monitor()
    frag = _extract_selfcheck_js(html)
    # 将 UTC 毫秒反推为「北京时间字符串」，使 parseBeijing 能折回原 UTC 毫秒。
    js = (
        "var stat = null;\n"
        + frag + "\n"
        + "function fmtBeijing(ms){\n"
        + "  var d = new Date(ms - (new Date().getTimezoneOffset() + 480) * 60000);\n"
        + "  function p(n){ return (n<10?'0':'')+n; }\n"
        + "  return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+' '+p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds());\n"
        + "}\n"
        + "var now = Date.now();\n"
        + "var ok5   = calcFreshness(fmtBeijing(now - 5*60000), now);\n"
        + "var warn20= calcFreshness(fmtBeijing(now - 20*60000), now);\n"
        + "var st40  = calcFreshness(fmtBeijing(now - 40*60000), now);\n"
        + "var lf    = calcFreshness('', now);\n"
        + "console.log(JSON.stringify({\n"
        + "  ok5_state: ok5.state, ok5_mins: ok5.mins,\n"
        + "  warn20_state: warn20.state, warn20_mins: warn20.mins,\n"
        + "  st40_state: st40.state, st40_mins: st40.mins,\n"
        + "  lf_state: lf.state, lf_mins: lf.mins\n"
        + "}));\n"
    )
    f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    try:
        f.write(js)
    finally:
        f.close()
    try:
        r = subprocess.run(["node", f.name], capture_output=True, text=True)
    finally:
        os.unlink(f.name)
    assert r.returncode == 0, "node 执行 calcFreshness 失败：\n%s\n%s" % (r.stdout, r.stderr)
    out = json.loads(r.stdout.strip().splitlines()[-1])

    assert out["ok5_state"] == "ok", "now-5 分钟应为 ok，实际 %s" % out["ok5_state"]
    assert out["warn20_state"] == "warn", "now-20 分钟应为 warn，实际 %s" % out["warn20_state"]
    assert out["warn20_mins"] == 20, "now-20 分钟 mins 应为 20，实际 %s" % out["warn20_mins"]
    assert out["st40_state"] == "stale", "now-40 分钟应为 stale，实际 %s" % out["st40_state"]
    assert out["lf_state"] == "loadfail", "空串应为 loadfail，实际 %s" % out["lf_state"]
    assert out["lf_mins"] is None, "loadfail 时 mins 应为 null，实际 %s" % out["lf_mins"]


# 跨时区不变量验证：各时区 7 月（含 DST）的预期 getTimezoneOffset（分钟）
#   Asia/Shanghai 无 DST → -480（UTC+8）
#   UTC                → 0
#   America/New_York  7 月 EDT（UTC-4）→ +240
#   Europe/London     7 月 BST（UTC+1）→ -60
_TZ_ZONES = [
    ("Asia/Shanghai", -480),
    ("UTC", 0),
    ("America/New_York", 240),
    ("Europe/London", -60),
]


@pytest.mark.skipif(not _has_node(), reason="node 不可用，跳过跨时区 parseBeijing 校验")
def test_parse_beijing_timezone_invariant():
    """跨时区不变量：parseBeijing 在所有时区都必须返回「北京时间 21:30:52」的真实 UTC 毫秒。

    真实 UTC 基准用 Date.UTC(2026,6,10,13,30,52) 算出（北京时间 21:30:52 = UTC 13:30:52）。
    对每个时区分别用 subprocess 注入 TZ 环境变量启动 node 子进程，加载从 monitor.html
    抽出的 parseBeijing 源码，调用 parseBeijing("2026-07-10 21:30:52")，断言 === truth。

    这是真正能卡住「符号写反」的用例：旧写法 d.getTime() + (offset+480)*60000 在北京时区
    因 (offset+480)=0 而自抵消成「假绿」，但在 UTC(+8h)/纽约(+12h)/伦敦(+7h) 均偏差巨大；
    正确写法 d.getTime() - (offset+480)*60000 任一时区都 === truth。

    若环境不支持 TZ 覆盖（注入后 offset 未变化），则该时区 skip 并注明；但 UTC 与
    Asia/Shanghai 必须至少生效，否则整体 skip（环境不具备跨时区验证条件）。
    """
    html = _read_monitor()
    frag = _extract_selfcheck_js(html)

    js = (
        "var stat = null;\n"
        + frag + "\n"
        # 当前子进程实际生效的本地时区偏移（分钟）
        + "var offset = new Date().getTimezoneOffset();\n"
        # 北京时间 21:30:52 对应的真实 UTC 毫秒（绝对基准，与任何时区无关）
        + "var truth = Date.UTC(2026, 6, 10, 13, 30, 52);\n"
        + "var pb = parseBeijing('2026-07-10 21:30:52');\n"
        + "console.log(JSON.stringify({offset: offset, truth: truth, pb: pb}));\n"
    )

    tested = []
    skipped = []
    for zone, exp_offset in _TZ_ZONES:
        rc, stdout, stderr = _run_node_with_tz(js, zone)
        assert rc == 0, (
            "node 执行 parseBeijing（TZ=%s）失败：\n%s\n%s" % (zone, stdout, stderr)
        )
        out = json.loads(stdout.strip().splitlines()[-1])
        # 注入的 TZ 是否真正生效：实际 offset 与预期一致（容差 1 分钟）
        if abs(out["offset"] - exp_offset) <= 1:
            assert out["pb"] == out["truth"], (
                "TZ=%s 下 parseBeijing 跨时区偏差："
                "parseBeijing=%s, 期望真实 UTC=%s（差 %s ms）"
                % (zone, out["pb"], out["truth"], out["pb"] - out["truth"])
            )
            tested.append(zone)
        else:
            skipped.append(zone)

    # UTC 与 Asia/Shanghai 是必验时区；若二者因环境不支持 TZ 覆盖而未生效，
    # 则本环境无法验证跨时区不变量，整体 skip 并注明，避免误判为通过。
    missing_required = [z for z in ("UTC", "Asia/Shanghai") if z in skipped]
    if missing_required:
        pytest.skip(
            "当前环境不支持 TZ 环境变量覆盖（%s 未生效），无法验证跨时区不变量；"
            "已跳过时区：%s" % (", ".join(missing_required), ", ".join(skipped) or "无")
        )
