"""Phase 0 止血回归测试：内置默认 Token 反转 + 小红书幽灵功能清理。

本测试验证「阶段 0」两类事项在后续改动中不被回归：

1. 内置默认 Token（monitor.html）——【已按用户明确决定反转】
   阶段 0 曾做「移除内置 Token」的安全 hardening，但用户已明确反转该决定：
   现在 monitor.html 重新内置一个默认 GitHub Token（DEFAULT_GH_TOKEN）作为
   getGhToken() 的兜底返回值，使增删监控开箱即用（无需用户自行配置 Token）。
   因此本测试不再断言「无泄露 PAT / 无内置 Token 变量」，改为断言：
   - monitor.html 存在 ``var DEFAULT_GH_TOKEN=`` 赋值，且 getGhToken 在用户无
     localStorage Token 时回退到该内置常量；
   - 配置页 / 连接检测文案中已就位「默认 Token」或「内置默认」字样。
   注意：本测试不断言具体 PAT 字串值。

2. 小红书幽灵功能清理（check_status.py / docs）——【保持不变】
   - ``check_status.py`` 不得把小红书当作「已实现」的检测分支/函数
     （允许「已移除 / 未支持」的注释性提及）。
   - ``docs/blive-monitor-context.md`` 与 ``docs/live-monitor-detection-landscape.md``
     不得再声称小红书「已端到端验证 / 15 单测 / 补了行业空白」等虚假声明，
     且应明确声明「未支持 / 已移除」。
"""

import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel_path: str) -> str:
    """读取仓库内相对路径文件内容（UTF-8）。"""
    with open(os.path.join(REPO_ROOT, rel_path), encoding="utf-8") as f:
        return f.read()


def test_monitor_html_getGhToken_builtin_fallback():
    """getGhToken 在用户无 localStorage Token 时回退到内置 DEFAULT_GH_TOKEN。

    用户已明确反转阶段 0 的「移除内置 Token」hardening：
    monitor.html 重新内置默认 Token 作为兜底，使增删监控开箱即用。
    本测试断言内置默认 Token 已就位，且文案说明其存在（不断言具体 PAT 值）。
    """
    html = _read("monitor.html")
    # 1) 存在内置默认 Token 变量赋值
    assert "var DEFAULT_GH_TOKEN=" in html, \
        "monitor.html 缺少内置默认 Token 变量赋值 (var DEFAULT_GH_TOKEN=)"

    # 2) getGhToken 在缺少用户 Token 时回退到内置常量
    assert "return DEFAULT_GH_TOKEN" in html, \
        "getGhToken 未在缺少用户 Token 时回退到内置 DEFAULT_GH_TOKEN"

    # 3) 配置页 / 连接检测文案已就位「默认 Token」或「内置默认」字样
    assert ("默认 Token" in html) or ("内置默认" in html), \
        "配置页 / 连接检测文案未说明内置默认 Token 已就位"



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
