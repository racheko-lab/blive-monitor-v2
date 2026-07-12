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

    # 换肤后房间链接统一使用新皮肤类 .blm-room-link（设计文档 §5：.act → .blm-room-link）。
    # live/offline 的视觉区分由文案（进入/查看直播间）+ 状态徽标（blm-live-badge /
    # blm-offline-badge）承担，不再依赖旧的 act / act-off 类。可点击性（u!=='#' 闸门）
    # 与链接 href 均保持不变。
    # live 房间：进入直播间 →，href 为 bilibili 直播间地址；class 为 blm-room-link
    assert "进入直播间" in out
    assert "https://live.bilibili.com/123" in out
    assert '<a class="blm-room-link" href="https://live.bilibili.com/123"' in out, (
        "live 房间链接 class 应为新皮肤类 blm-room-link"
    )
    assert "blm-live-badge" in out, (
        "live 房间应通过 blm-live-badge 呈现开播强调（替代旧 act/act-off 区分）"
    )
    # offline 房间：查看直播间 →，href 为 douyin 直播间地址；class 同样为 blm-room-link
    assert "查看直播间" in out
    assert "https://live.douyin.com/456" in out
    assert '<a class="blm-room-link" href="https://live.douyin.com/456"' in out, (
        "offline 房间链接 class 应为新皮肤类 blm-room-link"
    )
    assert "blm-offline-badge" in out, "offline 房间应通过 blm-offline-badge 呈现未开播状态"
    # 未知平台房间（u==='#'）：不应生成任何链接（live/offline 各 1 个 blm-room-link）
    assert out.count('class="blm-room-link"') == 2, (
        "live 与 offline 各应渲染 1 个 blm-room-link，未知平台不渲染，实际：%s" % out
    )
    assert 'href="#"' not in out, "未知平台不应渲染直播间链接"


# ==================== 颜色区分：开播/未开播按钮不应同色（结构性断言） ====================

def test_room_link_css_rule_exists():
    """<style> 内必须存在 .blm-room-link 的 CSS 规则（换肤后取代旧 .act/.act-off）。"""
    html = _read_monitor()
    # 抽取 <style ...>...</style> 区块再做断言（换肤后 <style> 带 id 属性，须容忍属性）
    style = re.search(r"<style[^>]*>.*?</style>", html, re.S)
    assert style, "monitor.html 缺少 <style> 区块"
    style_text = style.group(0)
    assert re.search(r"\.blm-room-link\s*\{", style_text), (
        "应在 <style> 内定义 .blm-room-link 链接样式规则（取代旧 .act-off）"
    )
    # 复用已有品牌变量（--brand-primary / --brand-primary-light），不引入新变量
    assert "var(--brand-primary)" in style_text, (
        ".blm-room-link 应沿用已有 --brand-primary 品牌变量"
    )


def test_render_live_link_uses_blm_room_link_class():
    """renderLive 的房间链接构造（var linkHtml=）统一使用新皮肤类 blm-room-link，
    并通过 isLive 三元切换「进入/查看直播间」文案（替代旧 act / act-off 区分）。"""
    html = _read_monitor()
    line = [ln for ln in html.splitlines() if "var linkHtml=" in ln]
    assert line, "未找到 renderLive 内构造房间链接的行（var linkHtml=）"
    src = line[0]
    # 链接使用新皮肤类 blm-room-link（设计文档 §5：.act → .blm-room-link）
    assert '"blm-room-link"' in src, "房间链接 class 应改为 blm-room-link（换肤重命名）"
    # 文案按 isLive 区分：开播「进入直播间 →」、未开播「查看直播间 →」
    assert "isLive?'进入直播间 →':'查看直播间 →'" in src, "应按 isLive 区分进入/查看直播间文案"
    # 开播分支保留「进入直播间」（对应旧的醒目文案）
    assert "进入直播间" in src, "开播分支文案应为「进入直播间 →」"


def test_room_link_styled_and_live_offline_badge_distinct():
    """回归：房间链接 .blm-room-link 有定义样式（开播醒目品牌色），且 live/offline
    状态区分通过 .blm-live-badge / .blm-offline-badge 呈现（替代旧 act/act-off 配色区分）。"""
    html = _read_monitor()
    style = re.search(r"<style[^>]*>.*?</style>", html, re.S).group(0)
    # 链接有定义样式（使用品牌色变量，开播醒目）
    assert re.search(r"\.blm-room-link\s*\{", style)
    assert "var(--brand-primary)" in style
    # live/offline 状态区分徽标存在（取代旧 act-off 弱化配色）
    assert ".blm-live-badge" in html, "应存在 .blm-live-badge 开播徽标（区分 live/offline）"
    assert ".blm-offline-badge" in html, "应存在 .blm-offline-badge 未开播徽标（区分 live/offline）"


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

    # 换肤后 live / offline 房间链接统一使用 .blm-room-link（区分由文案+徽标呈现）
    assert '<a class="blm-room-link" href="https://live.bilibili.com/123"' in out
    assert '<a class="blm-room-link" href="https://live.douyin.com/456"' in out
    assert out.count('class="blm-room-link"') == 2
