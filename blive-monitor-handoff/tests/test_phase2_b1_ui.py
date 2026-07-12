"""阶段二 2a · B1 批量增删 UI 契约（grep）。

验证 monitor.html 中 B1 相关 UI 标记（批量框 id、导入导出函数、导入框/文件控件）
存在，满足 PRD §附录「新增契约」保护清单。纯函数逻辑由 test_phase2_b1_batch.py 验证。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")


def _src():
    return open(HTML, encoding="utf-8").read()


def test_batch_add_box_present():
    src = _src()
    assert 'id="batchAddBox"' in src, "直播视图缺少 batchAddBox 批量框"
    assert 'id="postBatchBox"' in src, "新作视图缺少 postBatchBox 批量框"
    # 解析预览 + 批量加入 handler
    assert "previewBatchBox(" in src
    assert "submitBatchBox(" in src


def test_export_import_controls_present():
    src = _src()
    assert "function exportRooms" in src, "缺少 exportRooms 函数"
    assert "function importRooms" in src, "缺少 importRooms 函数"
    assert 'id="importBox"' in src, "缺少 importBox 导入文本框"
    assert 'id="importFile"' in src, "缺少 importFile 文件输入"
    assert "onImportFile(" in src, "缺少 onImportFile 文件读取处理"
    # 导出文件名契约：blive-monitor-backup-YYYYMMDD.json
    assert "blive-monitor-backup-" in src, "导出文件名不符合 blive-monitor-backup-YYYYMMDD.json"
