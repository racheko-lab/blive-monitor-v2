"""P0-5 平台定位一致性守护：前端固化 + 死代码清理 + 无幽灵声明。

本测试锁定阶段 0「正式放弃小红书」决策的落地结果，防止回潮：

1. 前端固化（monitor.html）：``#view-config`` 顶部含 ``id="supportedPlatforms"``
   区块，且明确标注 B站/抖音「已支持」、小红书「已放弃，不计划支持」。
2. 数据契约（rooms.json）：无任何 ``platform == 'xhs'`` 条目。
3. 死代码清理（.github/workflows/check.yml）：无 ``Check xhs rooms`` 步骤、
   无 ``xhslist`` 引用。
4. 无幽灵声明（仅产品文档）：README / docs/blive-monitor-context.md /
   docs/live-monitor-detection-landscape.md 均不含「15 passed / 补了行业空白 /
   已实现小红书」等虚假声明；排除 docs/product_analysis.md（合法分析引用）与
   本期过程文档（PRD/设计稿自身）。
5. 重申（check_status.py）：无小红书实现函数（fetch/parse/query_xhs 等）。

全部采用文件系统读取（open + 正则/JSON），不执行 JS、不启动浏览器、不发网络请求，
与 tests/test_phase0_hardening.py 一致。
"""

import os
import re
import json

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel_path: str) -> str:
    """读取仓库内相对路径文件内容（UTF-8）。"""
    with open(os.path.join(REPO_ROOT, rel_path), encoding="utf-8") as f:
        return f.read()


def test_frontend_has_supported_platforms_block() -> None:
    """断言 1：monitor.html 含支持平台区块，且含「已支持」与「已放弃」标记。"""
    html = _read("monitor.html")
    assert 'id="supportedPlatforms"' in html
    assert "已支持" in html
    assert "已放弃，不计划支持" in html


def test_rooms_no_xhs() -> None:
    """断言 2：rooms.json 解析后无 platform == 'xhs' 条目。"""
    data = json.loads(_read("rooms.json"))
    assert not any(r.get("platform") == "xhs" for r in data)
    # 文本层面再加一层兜底：不得出现 "xhs" 字样
    assert '"xhs"' not in _read("rooms.json")


def test_workflow_no_xhs_dead_step() -> None:
    """断言 3：check.yml 无 Check xhs rooms 步骤、无 xhslist 引用。"""
    wf = _read(".github/workflows/check.yml")
    assert "Check xhs rooms" not in wf
    assert "xhslist" not in wf


def test_no_ghost_claims() -> None:
    """断言 4：仅扫描产品文档，不含幽灵声明短语。

    扫描范围：README.md + docs/blive-monitor-context.md +
    docs/live-monitor-detection-landscape.md。
    排除：docs/product_analysis.md（合法分析引用，正文以「实际这些全部不存在」否定）、
    本期过程文档（PRD/设计稿自身）以免自我误报。
    """
    targets = [
        "README.md",
        "docs/blive-monitor-context.md",
        "docs/live-monitor-detection-landscape.md",
    ]
    # 幽灵声明短语（正则匹配，re.escape 防止特殊字符误用）
    ghosts = [
        "15 passed",
        "15 单测",
        "15 passed in",
        "补了行业空白",
        "行业空白",
        "已端到端验证",
        "已实现小红书",
        "test_check_xhs",
        "test_check_xiaohongshu",
        "最关键的技术突破",
        "填补了行业",
    ]
    pattern = re.compile("|".join(re.escape(g) for g in ghosts))
    for t in targets:
        doc = _read(t)
        hit = pattern.search(doc)
        assert hit is None, f"{t} 含幽灵声明: {hit.group(0)!r}"


def test_check_status_no_xhs_branch() -> None:
    """断言 5：check_status.py 无小红书实现函数（重申）。"""
    src = _read("check_status.py")
    xhs_funcs = (
        "fetch_xiaohongshu",
        "parse_xiaohongshu",
        "query_xiaohongshu",
        "fetch_xhs",
        "parse_xhs",
        "_extract_xhs_state",
    )
    for fn in xhs_funcs:
        assert fn not in src, f"check_status.py 仍存在小红书实现: {fn}"
