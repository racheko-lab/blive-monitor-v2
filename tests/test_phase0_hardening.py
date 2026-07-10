"""Phase 0 止血回归测试：安全 Token 移除 + 小红书幽灵功能清理。

本测试验证「阶段 0（止血）」的两类修复在后续改动中不被回归：

1. 安全止血（monitor.html）
   - 不得再包含历史上硬编码在源码里的全权限 GitHub PAT 字串
     （或其拼接片段），也不得引用当初硬编码在源码里的内置 Token 变量。
   - ``getGhToken()`` 不再回退到任何内置 Token；连接检测文案不再提示
     「使用内置默认 Token」。

2. 小红书幽灵功能清理（check_status.py / docs）
   - ``check_status.py`` 不得把小红书当作「已实现」的检测分支/函数
     （允许「已移除 / 未支持」的注释性提及）。
   - ``docs/blive-monitor-context.md`` 与 ``docs/live-monitor-detection-landscape.md``
     不得再声称小红书「已端到端验证 / 15 单测 / 补了行业空白」等虚假声明，
     且应明确声明「未支持 / 已移除」。

注意：历史泄露 Token 的片段在本测试文件中以「拆分拼接」方式构造，
避免出现完整字串，防止本测试文件本身再次成为泄露点。
"""

import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel_path: str) -> str:
    """读取仓库内相对路径文件内容（UTF-8）。"""
    with open(os.path.join(REPO_ROOT, rel_path), encoding="utf-8") as f:
        return f.read()


# 历史泄露 PAT 的片段（拆分拼接，避免本文件出现完整字串）。
_PAT_FRAG_A = "ghp_v4XmZ" + "6xQ32Pq5TII"
_PAT_FRAG_B = "4sOcaBH500J" + "CL44dHicP"
LEAKED_PAT_FRAGMENTS = (_PAT_FRAG_A, _PAT_FRAG_B)

# 内置 Token 变量名（同样拆分，避免本文件出现完整字串）。
_BUILTIN_TOKEN_VAR = "GH_TOKEN_BUILT" + "IN"


def test_monitor_html_no_leaked_pat():
    """monitor.html 不得包含泄露的全权限 PAT 字串或其拼接片段。"""
    html = _read("monitor.html")
    for bad in LEAKED_PAT_FRAGMENTS:
        assert bad not in html, f"monitor.html 仍包含泄露字串片段: {bad}"


def test_monitor_html_no_builtin_token_reference():
    """monitor.html 不得再引用当初硬编码在源码里的内置 Token 变量。"""
    html = _read("monitor.html")
    assert _BUILTIN_TOKEN_VAR not in html, \
        "monitor.html 仍引用当初硬编码在源码里的内置 Token 变量"


def test_monitor_html_getGhToken_no_builtin_fallback():
    """getGhToken 不应再回退到内置 Token，连接检测文案不再提「内置默认 Token」。"""
    html = _read("monitor.html")
    # 函数体不应再回退到内置 Token 变量
    assert "return " + _BUILTIN_TOKEN_VAR not in html, \
        "getGhToken 仍回退到内置 Token"
    # 连接检测提示不应再声称「使用内置默认 Token」
    assert "内置默认 Token" not in html, \
        "连接检测文案仍提及「内置默认 Token」"


def test_check_status_no_xhs_implemented_branch():
    """check_status.py 不得把小红书当作「已实现」的检测逻辑。

    允许「已移除 / 未支持 / 不支持」的注释性提及。
    """
    src = _read("check_status.py")

    # 不允许存在小红书「已实现」的检测函数 / 分支入口
    forbidden_funcs = (
        "fetch_xiaohongshu",
        "parse_xiaohongshu",
        "query_xiaohongshu",
        "fetch_xhs",
        "parse_xhs",
        "_extract_xhs_state",
        "_render_with_chromium",
    )
    for tok in forbidden_funcs:
        assert tok not in src, f"check_status.py 仍存在小红书实现函数: {tok}"

    # 若代码中存在 xiaohongshu / 小红书 / xhs 的提及，必须搭配
    # 「移除 / 未支持 / 不支持」标注，否则视为把小红书当正常平台。
    pattern = re.compile(r"xiaohongshu|小红书|xhs", re.IGNORECASE)
    for m in pattern.finditer(src):
        start = src.rfind("\n", 0, m.start()) + 1
        end = src.find("\n", m.end())
        if end == -1:
            end = len(src)
        line = src[start:end]
        assert (
            ("移除" in line)
            or ("未支持" in line)
            or ("不支持" in line)
            or ("removed" in line.lower())
        ), f"check_status.py 中对小红书的提及未标明「已移除/未支持」: {line.strip()}"


def test_docs_no_xhs_false_claims():
    """两份上下文文档不得声称小红书「已端到端验证 / 15 单测 / 补行业空白」。"""
    targets = {
        "docs/blive-monitor-context.md": _read("docs/blive-monitor-context.md"),
        "docs/live-monitor-detection-landscape.md": _read(
            "docs/live-monitor-detection-landscape.md"
        ),
    }

    false_claims = (
        "端到端验证",
        "已端到端验证",
        "15 单测",
        "15 passed",
        "test_check_xhs",
        "补了行业空白",
        "补空白",
        "最关键的技术突破",
    )

    for name, doc in targets.items():
        for bad in false_claims:
            assert bad not in doc, f"{name} 仍包含虚假小红书声明: {bad}"
        # 必须明确声明「未支持 / 已移除 / 未实现」
        assert (
            ("未支持" in doc) or ("已移除" in doc) or ("未实现" in doc)
        ), f"{name} 未明确声明小红书未支持/已移除"
