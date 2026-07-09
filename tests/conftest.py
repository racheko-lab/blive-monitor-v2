"""pytest 配置：将仓库根目录加入 sys.path，使 tests/ 能导入顶层模块。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


import pytest


@pytest.fixture(autouse=True)
def _isolate_dedup_ledger(tmp_path, monkeypatch):
    """隔离通知去重账本：每个用例用独立临时文件，杜绝跨用例污染。

    缺此 fixture 时，notify_dedup.json 在用例间共享，导致依赖推送的用例出现
    顺序依赖（单独跑失败、全量跑因排在正确位置而通过）。恢复仓库时该 fixture
    随未授权提交一并被剔除，这里补回以保证套件确定性。
    """
    import notify_dedup
    monkeypatch.setattr(notify_dedup, "LEDGER_FILE", str(tmp_path / "notify_dedup.json"))

