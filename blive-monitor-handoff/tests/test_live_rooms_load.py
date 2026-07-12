"""无 Token 降级分支（ld() 内读取 rooms.json）功能回归测试。

背景：阶段0 提交 bbc123f 移除了硬编码默认 PAT，导致无 Token 时 ld() 走到
rooms.json 静态文件降级分支。该分支曾把 `data:r.json()` 的 Promise 直接赋给
data，使 rooms 变成 Promise，renderLive() 首行 `if(!rooms.length)` 恒为真，
直播 tab 永远显示「📭 暂无监控房间」。

本测试用 pytest 调用真实 node 执行该分支表达式，断言：
  - 无 Token 时返回 {ok:true, data: Array(2)}（data 是数组而非 Promise）；
并加结构性断言：monitor.html 该分支必须含 `await r.json()`，且不得再出现
`data:r.json()}` 这种把 Promise 直接赋给 data 的写法（防止 await 被改回）。
无 node 时跳过（不报错）。
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


def _extract_no_token_branch(html: str) -> str:
    """从 monitor.html 抽取无 Token 降级分支的表达式片段。

    该分支以 `fetch('rooms.json?_='` 开头，并以 `return {ok:false}` 的
    `.catch(function(){return {ok:false};})` 收尾——全文件中仅此一处同时满足
    「rooms.json fetch」+「return {ok:false}」（有 Token 分支走 apiGetRooms，
    另一处 rooms.json fetch 兜底的 catch 返回 [] 而非 {ok:false}），因此可唯一定位。
    """
    pat = (
        r"fetch\('rooms\.json\?_='"
        r".*?\}\)\.catch\(function\(\)\{return \{ok:false\};\}\)"
    )
    m = re.search(pat, html, re.S)
    assert m, (
        "未能从 monitor.html 定位无 Token 降级分支"
        "（rooms.json fetch + catch 返回 {ok:false}）"
    )
    return m.group(0)


# ==================== 结构性断言（不依赖 node） ====================

def test_no_token_branch_uses_await_r_json():
    """回归闸门：降级分支不得再把 Promise 直接赋给 data。

    - 全文件不应再出现 'data:r.json()}'（把 r.json() 的 Promise 直接赋给 data）；
    - 抽出的无 Token 分支应包含 `await r.json()` 且其 .then 回调为 async。
    """
    html = _read_monitor()
    assert "data:r.json()}" not in html, (
        "无 Token 分支不应再出现 'data:r.json()}' 这种把 Promise 直接赋给 data 的写法"
    )
    frag = _extract_no_token_branch(html)
    assert "await r.json()" in frag, "无 Token 分支应对 r.json() 使用 await"
    assert "async function(r)" in frag, (
        "无 Token 分支的 .then 回调应为 async，否则 await r.json() 无法生效"
    )


# ==================== 功能性断言（node 实跑降级分支） ====================

@pytest.mark.skipif(not _has_node(), reason="node 不可用，跳过前端真实加载分支校验")
def test_no_token_branch_resolves_array_not_promise():
    """用 node 实跑无 Token 降级分支：mock fetch 返回 2 个房间对象，断言
    rooms.data 是长度 2 的数组（而非 Promise/其它类型）。"""
    html = _read_monitor()
    frag = _extract_no_token_branch(html)

    mock_rooms = [
        {"platform": "bilibili", "id": "123", "name": "Room A"},
        {"platform": "douyin", "id": "456", "name": "Room B"},
    ]

    js = (
        "var t = Date.now();\n"
        "global.AbortSignal = { timeout: function(){ return null; } };\n"
        "var fetch = async function(url, opts){\n"
        "  return { ok: true, json: async function(){ return %s; } };\n"
        "};\n"
        "var result = %s;\n"
        "result.then(function(v){\n"
        "  console.log(JSON.stringify({\n"
        "    ok: v && v.ok,\n"
        "    isArray: Array.isArray(v && v.data),\n"
        "    len: (v && v.data && v.data.length) || -1,\n"
        "    dataType: typeof (v && v.data)\n"
        "  }));\n"
        "}).catch(function(e){\n"
        "  console.log(JSON.stringify({ error: String((e && e.stack) || e) }));\n"
        "});\n"
    ) % (json.dumps(mock_rooms), frag)

    f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    try:
        f.write(js)
    finally:
        f.close()
    try:
        r = subprocess.run(["node", f.name], capture_output=True, text=True)
    finally:
        os.unlink(f.name)

    assert r.returncode == 0, "node 执行无 Token 降级分支失败：\n%s\n%s" % (r.stdout, r.stderr)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as ex:
        raise AssertionError(
            "无法解析 node 输出：%s\nstdout=%s\nstderr=%s" % (ex, r.stdout, r.stderr)
        )

    assert "error" not in out, "无 Token 降级分支执行抛错：%s" % out.get("error")
    assert out["ok"] is True, "无 Token 分支应返回 ok:true，实际：%s" % out
    assert out["isArray"] is True, (
        "rooms.data 应为数组而非 Promise/其它类型；"
        "实际 dataType=%s, len=%s" % (out["dataType"], out["len"])
    )
    assert out["len"] == 2, (
        "rooms.data 应含 2 个房间，实际 len=%s, dataType=%s"
        % (out["len"], out["dataType"])
    )
