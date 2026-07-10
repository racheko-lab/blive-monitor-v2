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

    # live 房间：进入直播间 →，href 为 bilibili 直播间地址
    assert "进入直播间" in out
    assert "https://live.bilibili.com/123" in out
    # offline 房间：查看直播间 →，href 为 douyin 直播间地址
    assert "查看直播间" in out
    assert "https://live.douyin.com/456" in out
    # 未知平台房间（u==='#'）：不应生成任何 class="act" 链接
    assert out.count('<a class="act"') == 2, (
        "仅 live 与 offline 两个合法平台房间应有可点击链接，实际：%s" % out
    )
    assert 'href="#"' not in out, "未知平台不应渲染直播间链接"
