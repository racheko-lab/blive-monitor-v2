"""P0-4 列表批量搜索：直播/新作 tab 文本搜索（本轮 = 纯前端文本搜索 + 筛选）。

背景：P0-4 在 monitor.html 增加全局搜索词 `q`（与 `fl` 并列），在直播/新作两个 tab 各加
一个搜索框，输入即按 name/id（新作追加 nickname）做大小写不敏感子串过滤，与平台 chip
（fl）AND 叠加；过滤后为空且 q 非空时显示「未找到匹配「xxx」」而非「暂无监控…」。
搜索路径只重渲染 body，绝不调用 ld()、不发网络请求、不碰健康条。

本测试沿用仓库既有 pytest + 真实 node 实跑 JS 的范式（参考 test_selfcheck.py /
test_live_rooms_load.py）：

  - 结构性断言（不依赖 node）：monitor.html 必须含 #liveSearch、#postsSearch、
    onLiveSearch、onPostsSearch、matchQ、matchPostQ、全局 q（fl='all',q=''）。
  - 功能性断言（node 实跑抽出的 matchQ/matchPostQ 源码）：
      1) matchQ 命中 / 不命中 / 大小写不敏感；
      2) matchPostQ 命中 nickname（postTrack['douyin_'+id].nickname）。

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


def _extract_match_js(html: str) -> str:
    """从 monitor.html 抽取 matchQ + matchPostQ 源码（两函数紧邻，位于 renderLive 前）。

    定位锚：从 `function matchQ` 非贪婪匹配到下一个 `\\nfunction renderLive` 之前，
    全文件仅此一处同时满足「matchQ 定义」+「紧邻 renderLive」的边界，可唯一定位。
    """
    pat = r"function matchQ\(.*?\nfunction renderLive"
    m = re.search(pat, html, re.S)
    assert m, "未能从 monitor.html 定位 matchQ/matchPostQ 源码段（matchQ … renderLive 前）"
    return m.group(0).replace("\nfunction renderLive", "")


def _extract_render_posts_js(html: str) -> str:
    """从 monitor.html 抽取 renderPosts 源码（含其后的结束大括号，到下一个具名函数 typeMeta 前）。

    renderPosts 内部仅用匿名回调（function(...)），不含其他具名函数定义，
    故 `function renderPosts(.*?)\\nfunction typeMeta` 非贪婪匹配可唯一定位该段。
    """
    pat = r"function renderPosts\(.*?\nfunction typeMeta"
    m = re.search(pat, html, re.S)
    assert m, "未能从 monitor.html 定位 renderPosts 源码段（renderPosts … typeMeta 前）"
    return m.group(0).replace("\nfunction typeMeta", "")


# ==================== 结构性断言（不依赖 node） ====================

def test_search_dom_and_symbols_present():
    """结构性闸门：搜索框 id、handler、匹配函数、全局 q 必须齐备。"""
    html = _read_monitor()
    assert 'id="liveSearch"' in html, "缺少直播搜索框 #liveSearch"
    assert 'id="postsSearch"' in html, "缺少新作搜索框 #postsSearch"
    assert "onLiveSearch" in html, "缺少 onLiveSearch handler"
    assert "onPostsSearch" in html, "缺少 onPostsSearch handler"
    assert "function matchQ" in html, "缺少 matchQ 匹配函数"
    assert "function matchPostQ" in html, "缺少 matchPostQ 匹配函数"
    # 全局 q：与 fl 并列声明 `fl='all',q=''`
    assert re.search(r"fl='all',q=''", html), "缺少全局搜索词 q 的声明（应与 fl 并列）"


def test_match_js_extractable():
    """matchQ/matchPostQ 源码段可被稳定抽取（保证 node 实跑不会因定位失败而漏测）。"""
    html = _read_monitor()
    frag = _extract_match_js(html)
    assert "function matchQ" in frag, "抽出的代码段缺少 matchQ"
    assert "function matchPostQ" in frag, "抽出的代码段缺少 matchPostQ"
    assert "postTrack['douyin_' + r.id]" in frag, "matchPostQ 应引用 postTrack 的 nickname"


# ==================== 功能性断言（node 实跑） ====================

@pytest.mark.skipif(not _has_node(), reason="node 不可用，跳过匹配函数实跑校验")
def test_matchQ_behavior():
    """matchQ：name/id 子串命中、不命中、大小写不敏感。"""
    html = _read_monitor()
    frag = _extract_match_js(html)
    js = (
        frag + "\n"
        + "console.log(JSON.stringify({\n"
        + "  hit_name: matchQ({name:'小猪装机', id:'wsyzxz6688'}, '小猪'),\n"
        + "  miss: matchQ({name:'峰哥', id:'22230707'}, 'douyin'),\n"
        + "  ci: matchQ({name:'小猪装机', id:'wsyzxz6688'}, 'WSYZXZ6688'),\n"
        + "  empty_query: matchQ({name:'峰哥', id:'22230707'}, '')\n"
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
    assert r.returncode == 0, "node 执行 matchQ 失败：\n%s\n%s" % (r.stdout, r.stderr)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["hit_name"] is True, "matchQ 应按 name 子串命中『小猪』，实际 %s" % out
    assert out["miss"] is False, "matchQ 对不匹配的『douyin』应返回 false，实际 %s" % out
    # 大小写不敏感：name 为中文『小猪装机』，pinyin『XIAOZHU』并非其子串，无法命中；
    # 故改用 ASCII 字段 id 的大写变体演示——'WSYZXZ6688' 应命中 id 'wsyzxz6688'。
    assert out["ci"] is True, "matchQ 应大小写不敏感命中 id 的大写变体『WSYZXZ6688』，实际 %s" % out
    assert out["empty_query"] is True, "matchQ 空搜索词应命中一切（s='' 为任意串子串），实际 %s" % out


@pytest.mark.skipif(not _has_node(), reason="node 不可用，跳过匹配函数实跑校验")
def test_matchPostQ_nickname_hit():
    """matchPostQ：nickname（postTrack['douyin_'+id].nickname）命中。

    注：匹配是大小写不敏感「子串」匹配（设计 §3.5），故 q 必须是 nickname 的实际子串。
    此处 fixture 严格使用设计所给数据 nickname='小猪装机'，q 取其中文子串『小猪』以验证
    nickname 字段确实参与匹配；英文 pinyin『xiaozhu』并非 nickname 的子串，子串匹配无法命中。
    """
    html = _read_monitor()
    frag = _extract_match_js(html)
    js = (
        "var postTrack = {'douyin_83134194400': {nickname: '小猪装机'}};\n"
        + frag + "\n"
        + "console.log(JSON.stringify({\n"
        + "  nickname_hit: matchPostQ({id:'83134194400', name:''}, '小猪'),\n"
        + "  id_hit: matchPostQ({id:'83134194400', name:''}, '83134194400'),\n"
        + "  miss: matchPostQ({id:'83134194400', name:''}, '不存在的词')\n"
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
    assert r.returncode == 0, "node 执行 matchPostQ 失败：\n%s\n%s" % (r.stdout, r.stderr)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["nickname_hit"] is True, "matchPostQ 应按 nickname『小猪装机』命中『小猪』，实际 %s" % out
    assert out["id_hit"] is True, "matchPostQ 应按 id 命中，实际 %s" % out
    assert out["miss"] is False, "matchPostQ 对不匹配词应返回 false，实际 %s" % out


# ==================== 回归测试：锁死 renderPosts 搜索渲染 bug ====================

@pytest.mark.skipif(not _has_node(), reason="node 不可用，跳过 renderPosts 实跑校验")
def test_renderPosts_search_renders_filtered_list():
    """回归测试：renderPosts 在 q 命中子集时，必须渲染「过滤后的 list」而非「原数组前 N 条」。

    复现 P0-4 真实 bug：修复前循环写成 `var r=postRooms[i]`（遍历原数组），
    导致搜索态下渲染出来的是原数组前 N 条（多为未命中者），漏掉真正命中的条目。

    构造：postRooms=[阿A, 小宝, 中C, 小迪]，仅小宝/小迪 的 postTrack 有 nickname，
    q='小'。命中者应为 [小宝, 小迪]（按 name/nickname 子串），阿A/中C 不命中。
    断言捕获的 postsBody.innerHTML：含『小宝』且含『小迪』且不含『阿A』。
    若该 bug 复现（改用 postRooms[i]），会渲染出阿A、漏掉小迪 → 本用例 FAIL，从而锁死回归。
    """
    html = _read_monitor()
    match_frag = _extract_match_js(html)        # 真实 matchPostQ（含 postTrack 引用）
    render_frag = _extract_render_posts_js(html)  # 真实 renderPosts

    # 最小 DOM 桩：捕获 innerHTML / textContent
    js = (
        "// ---- 最小 DOM 桩 ----\n"
        "var _postsBody = { innerHTML: '' };\n"
        "var _postsCount = { textContent: '' };\n"
        "document = { getElementById: function(id){\n"
        "  if(id === 'postsBody') return _postsBody;\n"
        "  if(id === 'postsCount') return _postsCount;\n"
        "  return null;\n"
        "} };\n"
        "\n"
        "// ---- renderPosts 依赖的全局桩 ----\n"
        "var postRooms = ["
        "{id:'a',name:'阿A'},{id:'b',name:'小宝'},{id:'c',name:'中C'},{id:'d',name:'小迪'}];\n"
        "var postTrack = {'douyin_b':{nickname:'小宝'},'douyin_d':{nickname:'小迪'}};\n"
        "var hasApi = false;\n"
        "var q = '小';\n"
        "function removePostRoom(){}\n"
        "function e(s){ return String(s == null ? '' : s)"
        ".replace(/&/g,'&amp;').replace(/</g,'&lt;')"
        ".replace(/>/g,'&gt;').replace(/\"/g,'&quot;'); }\n"
        "function ago(){ return ''; }\n"
        "\n"
        + match_frag + "\n"
        + render_frag + "\n"
        "\n"
        "renderPosts();\n"
        "console.log(JSON.stringify({html: _postsBody.innerHTML, count: _postsCount.textContent}));\n"
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
    assert r.returncode == 0, "node 执行 renderPosts 失败：\n%s\n%s" % (r.stdout, r.stderr)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    html_out = out["html"]
    assert "小宝" in html_out, "搜索 q='小' 应渲染命中者『小宝』，实际输出：\n%s" % html_out
    assert "小迪" in html_out, "搜索 q='小' 应渲染命中者『小迪』，实际输出：\n%s" % html_out
    assert "阿A" not in html_out, (
        "回归失败：渲染出了未命中的『阿A』，说明仍遍历原数组 postRooms[i] 而非过滤后的 list[i]。\n"
        "实际输出：\n%s" % html_out
    )
    # 计数应为 匹配 2 / 4
    assert "匹配 2 / 4" in out["count"], "搜索计数应为『匹配 2 / 4』，实际：%s" % out["count"]
