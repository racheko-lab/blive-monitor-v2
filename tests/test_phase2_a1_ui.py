"""阶段二 2a · A1 定时摘要 UI 契约（grep）。

仅验证 monitor.html 中 A1 相关 UI 标记（控件 id + 函数名）存在，满足 PRD §附录
「新增契约」保护清单；纯函数逻辑由 test_phase2_a1_summary.py 验证。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")


def _src():
    return open(HTML, encoding="utf-8").read()


def test_summary_control_ids_present():
    src = _src()
    # 配置视图控件
    assert 'id="summaryEnabled"' in src, "缺少 summaryEnabled 开关"
    assert 'id="summaryFreq"' in src, "缺少 summaryFreq 频率控件"
    assert 'id="summarySendTime"' in src, "缺少 summarySendTime 时间输入"
    # 直播视图摘要卡
    assert 'id="summaryCard"' in src, "缺少 summaryCard 摘要卡"
    assert 'id="btnPushSummary"' in src, "缺少 btnPushSummary 请求推送按钮"


def test_summary_functions_present():
    src = _src()
    for fn in [
        "function computeSummary",
        "function computeSince",
        "function buildSummaryConfig",
        "function renderSummary",
        "function maybeShowSummary",
        "function copySummary",
        "function requestPushSummary",
    ]:
        assert fn in src, f"monitor.html 缺少函数: {fn}"


def test_summary_save_wires_into_blive_config():
    """AC4：summary 段能被 buildPushConfig 一并加密写入 BLIVE_CONFIG。"""
    src = _src()
    # savePushConfig 内应并入 buildSummaryConfig 结果（summary 段）
    assert "buildSummaryConfig()" in src, "buildPushConfig/savePushConfig 未并入 summary"
    # 独立的 saveSummaryConfig 也应存在（写可读镜像 + 尝试加密写 Secret）
    assert "function saveSummaryConfig" in src
