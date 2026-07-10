"""直播 tab（renderLive）直播间链接可点击性测试（快速模式小特性）。

需求：未开播(offline/replay/error/pending)的房间也应能点进直播间，
之前仅 live 状态才渲染「进入直播间 →」链接，现在放宽为「只要有合法
直播间 URL（u!=='#'）就渲染链接」，非 live 状态文案改为「查看直播间 →」。

测试分两类：
  1) 结构性断言：monitor.html 中 act 不再仅以 st==='live' 为唯一闸门；
  2) 功能性断言：用 node 抽取真实 renderLive() 与 e()，置于最小 DOM/全局
     桩中实跑，构造「live + offline + 未知平台」三类 mock 房间，校验
     liveBody.innerHTML 的链接文案与 href。无 node 时 skip（不报错）。
"""
import json
import os
import re
import subprocess

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


def _extract_js(html: str, sig: str) -> str:
    """从 monitor.html 提取某个顶层多行 function 的完整源码（闭合 `}` 位于行首）。"""
    m = re.search(re.escape(sig) + r"\{.*?\n\}", html, re.S)
    assert m, f"未能从 monitor.html 提取 {sig}"
    return m.group(0)


def _extract_single_line_js(html: str, sig: str) -> str:
    """提取某个单行 function 的完整源码（函数体不含 `}`）。"""
    m = re.search(re.escape(sig) + r"\{[^}]*\}", html)
    assert m, f"未能从 monitor.html 提取单行函数 {sig}"
    return m.group(0)


# ==================== 结构性断言（不依赖 node） ====================

def test_live_room_link_not_gated_only_on_live():
    """回归闸门：act 链接不再仅以 st==='live' 为唯一条件；应放宽为合法 u，
    且同时存在 live 文案「进入直播间 →」与非 live 文案「查看直播间 →」。"""
    html = _read_monitor()
    assert "u!=='#'" in html, "act 链接应放宽为 u!=='#' 闸门（未知平台不渲染）"
    assert "进入直播间" in html, "live 状态仍保留「进入直播间 →」文案"
    assert "查看直播间" in html, "应新增「查看直播间 →」文案供非 live 状态使用"
    # 旧的「仅 live」写法应已被移除
    assert "(s&&st==='live')" not in html, "不应再仅以 st==='live' 为唯一闸门"


# ==================== 功能性断言（node 抽取真实函数实跑） ====================

@pytest.mark.skipif(not _has_node(), reason="node 不可用，跳过前端真实函数校验")
def test_live_offline_unknown_rooms_link_behavior():
    """实跑 monitor.html 内 renderLive()：
      - live 房间(bilibili)  → 「进入直播间 →」，href=https://live.bilibili.com/<id>
      - offline 房间(douyin) → 「查看直播间 →」，href=https://live.douyin.com/<id>
      - 未知平台房间(u==='#') → 不渲染任何 class="act" 链接
    """
    html = _read_monitor()
    e_js = _extract_single_line_js(html, "function e(s)")
    render_js = _extract_js(html, "function renderLive()")

    rooms = [
        {"platform": "bilibili", "id": "123", "name": "Room A"},
        {"platform": "douyin", "id": "456", "name": "Room B"},
        {"platform": "unknown", "id": "789", "name": "Room C"},
    ]
    stat = {
        "updated": "2026-07-10 10:00",
        "rooms": [
            {"platform": "bilibili", "id": "123", "name": "Room A",
             "status": "live", "title": "直播标题", "online": 100},
            {"platform": "douyin", "id": "456", "name": "Room B",
             "status": "offline", "title": "未开播标题"},
            {"platform": "unknown", "id": "789", "name": "Room C",
             "status": "offline"},
        ],
    }

    harness = (
        "var liveBody = { innerHTML: '' };\n"
        "var document = { getElementById: function(id){"
        " return id === 'liveBody' ? liveBody : { innerHTML: '' }; } };\n"
        "var rooms = %s;\n"
        "var stat = %s;\n"
        "var fl = 'all';\n"
        "var hasApi = true;\n"
        + "var q = '';\n"  # P0-4：renderLive 现依赖全局搜索词 q（空串=不过滤）
        + "var matchQ = function(r, q){ return true; };\n"  # 桩：q 为空时不会被调用，提供以防万一
        "%s\n"   # e()
        "%s\n"   # renderLive()
        "renderLive();\n"
        "console.log(JSON.stringify(liveBody.innerHTML));\n"
    ) % (json.dumps(rooms), json.dumps(stat), e_js, render_js)

    import tempfile
    f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    try:
        f.write(harness)
    finally:
        f.close()
    try:
        r = subprocess.run(["node", f.name], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip())
    finally:
        os.unlink(f.name)

    # live 房间：进入直播间 →，href 为 bilibili 直播间地址；class 为醒目纯 'act'（无弱化类）
    assert "进入直播间" in out
    assert "https://live.bilibili.com/123" in out
    assert '<a class="act" href="https://live.bilibili.com/123"' in out, (
        "live 房间链接 class 应为醒目纯 'act'"
    )
    assert ('<a class="act act-off" href="https://live.bilibili.com/123"' not in out), (
        "live 房间链接不应带弱化类 act-off"
    )
    # offline 房间：查看直播间 →，href 为 douyin 直播间地址；class 含弱化 'act-off'
    assert "查看直播间" in out
    assert "https://live.douyin.com/456" in out
    assert '<a class="act act-off" href="https://live.douyin.com/456"' in out, (
        "offline 房间链接 class 应带弱化类 act-off"
    )
    # 未知平台房间（u==='#'）：不应生成任何 class="act" 链接
    assert out.count('class="act"') == 1, (
        "仅 live 房间应使用纯 'act' 类（offline 用 act-off），实际：%s" % out
    )
    assert 'href="#"' not in out, "未知平台不应渲染直播间链接"


# ==================== 颜色区分：开播/未开播按钮不应同色（结构性断言） ====================

def test_act_off_css_rule_exists():
    """<style> 内必须存在 .act-off 的 CSS 规则，提供弱化次要配色。"""
    html = _read_monitor()
    # 抽取 <style>...</style> 区块再做断言，避免命中无关的字符串
    style = re.search(r"<style>.*?</style>", html, re.S)
    assert style, "monitor.html 缺少 <style> 区块"
    assert ".act-off{" in style.group(0), "应在 <style> 内定义 .act-off 弱化样式规则"
    # 复用已有变量（--text2 / --line），不引入新变量
    assert "var(--text2)" in style.group(0), ".act-off 应沿用已有 --text2 变量"
    assert "var(--line)" in style.group(0), ".act-off 应沿用已有 --line 变量"


def test_render_live_offline_branch_uses_act_off_class():
    """第 378 行 renderLive 的 act 链接构造：离线分支（st!=='live'）必须用
    'act act-off'，开播分支（st==='live'）仍用纯 'act'。"""
    html = _read_monitor()
    line = [ln for ln in html.splitlines() if "var act=(u!=='#')" in ln]
    assert line, "未找到 renderLive 内构造 act 链接的第 378 行"
    src = line[0]
    # 离线（非 live）分支：'act-off' 字面量
    assert "'act':'act act-off'" in src, "离线分支 class 应含 'act act-off' 字面量"
    # 三元整体：开播用 'act'、未开播用 'act act-off'
    assert "(st==='live'?'act':'act act-off')" in src, "应按 st==='live' 区分 class"
    # 开播分支不应带 act-off（左侧纯 'act' 出现在 'act-off' 文本之前）
    assert src.index("'act'") < src.index("act-off"), (
        "纯 'act' 应作为开播分支出现在 act-off 之前"
    )


def test_render_live_act_off_is_only_secondary_for_offline():
    """回归：.act 醒目样式保持不变（开播仍亮红底白字），仅新增 .act-off 弱化，
    两者明确区分、不共用同一配色。"""
    html = _read_monitor()
    style = re.search(r"<style>.*?</style>", html, re.S).group(0)
    # .act 仍使用亮红 var(--live) 底（开播醒目）
    assert ".act{" in style
    assert "background:var(--live)" in style
    # .act-off 不得等于 .act 的醒目配色（不得用亮红底白字）
    act_off_rule = re.search(r"\.act-off\{[^}]*\}", style)
    assert act_off_rule, "应存在单行的 .act-off{...} 规则"
    assert "var(--live)" not in act_off_rule.group(0), (
        ".act-off 不得使用与开播按钮相同的亮红底 var(--live)"
    )


@pytest.mark.skipif(not _has_node(), reason="node 不可用，跳过前端真实函数颜色校验")
def test_live_offline_room_classes_real_run():
    """实跑 renderLive()：断言 live 房间链接 class 为 'act'、offline 房间为
    'act act-off'（直接抽取真实函数，无 node 时 skip）。"""
    html = _read_monitor()
    e_js = _extract_single_line_js(html, "function e(s)")
    render_js = _extract_js(html, "function renderLive()")

    rooms = [
        {"platform": "bilibili", "id": "123", "name": "Room A"},
        {"platform": "douyin", "id": "456", "name": "Room B"},
    ]
    stat = {
        "updated": "2026-07-10 10:00",
        "rooms": [
            {"platform": "bilibili", "id": "123", "name": "Room A",
             "status": "live", "title": "直播标题", "online": 100},
            {"platform": "douyin", "id": "456", "name": "Room B",
             "status": "offline", "title": "未开播标题"},
        ],
    }

    harness = (
        "var liveBody = { innerHTML: '' };\n"
        "var document = { getElementById: function(id){"
        " return id === 'liveBody' ? liveBody : { innerHTML: '' }; } };\n"
        "var rooms = %s;\n"
        "var stat = %s;\n"
        "var fl = 'all';\n"
        "var hasApi = true;\n"
        + "var q = '';\n"  # P0-4：renderLive 现依赖全局搜索词 q（空串=不过滤）
        + "var matchQ = function(r, q){ return true; };\n"  # 桩：q 为空时不会被调用，提供以防万一
        "%s\n%s\n"
        "renderLive();\n"
        "console.log(JSON.stringify(liveBody.innerHTML));\n"
    ) % (json.dumps(rooms), json.dumps(stat), e_js, render_js)

    import tempfile
    f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    try:
        f.write(harness)
    finally:
        f.close()
    try:
        r = subprocess.run(["node", f.name], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip())
    finally:
        os.unlink(f.name)

    # live 房间 → 纯 'act'；offline 房间 → 'act act-off'
    assert '<a class="act" href="https://live.bilibili.com/123"' in out
    assert '<a class="act act-off" href="https://live.douyin.com/456"' in out
    assert out.count('class="act"') == 1
