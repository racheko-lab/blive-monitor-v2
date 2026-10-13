"""tools/reap_stuck_runs.py 单测（全打桩，不依赖外网）。

背景见 2026-10-07 事故：run 37438236822 卡在 waiting 状态 12 小时 22 分钟，
占着 live-check-v2 并发组坑位，导致之后每 5 分钟一次的触发全部 pending→cancelled，
监控静默停更且无告警。timeout-minutes 对 waiting 无效，故需外部看门狗。
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from tools import reap_stuck_runs as rr


NOW = datetime(2026, 10, 7, 5, 0, 0, tzinfo=timezone.utc)


def _run(rid, status, age_min):
    return {
        "id": rid,
        "status": status,
        "created_at": (NOW - timedelta(minutes=age_min)).isoformat().replace("+00:00", "Z"),
    }


# ==================== find_stuck ====================

def test_waiting_over_threshold_is_stuck():
    """waiting 且超过阈值 → 卡死（这正是 37438236822 的形态）。"""
    got = rr.find_stuck([_run(1, "waiting", 720)], NOW)
    assert [r["id"] for r in got] == [1]


def test_queued_over_threshold_is_stuck():
    got = rr.find_stuck([_run(2, "queued", 30)], NOW)
    assert [r["id"] for r in got] == [2]


def test_in_progress_never_reaped():
    """in_progress 交给 GitHub 自己的 timeout-minutes，绝不误杀慢但正常的抓取。"""
    assert rr.find_stuck([_run(3, "in_progress", 600)], NOW) == []


def test_finished_states_ignored():
    for st in ("completed", "cancelled", "skipped"):
        assert rr.find_stuck([_run(4, st, 999)], NOW) == []


def test_under_threshold_not_reaped():
    """一轮正常抓取 4~5 分钟，20 分钟阈值内不得误伤。"""
    assert rr.find_stuck([_run(5, "waiting", 3)], NOW) == []
    assert rr.find_stuck([_run(6, "queued", 19)], NOW) == []


def test_threshold_boundary_is_inclusive():
    assert len(rr.find_stuck([_run(7, "waiting", 20)], NOW)) == 1


def test_mixed_list_only_stuck_selected():
    runs = [
        _run(1, "waiting", 720),      # 卡死
        _run(2, "in_progress", 720),  # 正常（慢）
        _run(3, "completed", 720),    # 已完成
        _run(4, "queued", 1),         # 刚排队
        _run(5, "queued", 45),        # 卡死
    ]
    assert [r["id"] for r in rr.find_stuck(runs, NOW)] == [1, 5]


def test_malformed_entries_skipped():
    """缺字段 / 时间格式错误 → 跳过，不抛异常。"""
    bad = [
        {"id": 1, "status": "waiting"},                       # 缺 created_at
        {"id": 2, "status": "waiting", "created_at": "xx"},   # 坏时间
        {"id": 3, "status": "waiting", "created_at": None},
    ]
    assert rr.find_stuck(bad, NOW) == []


def test_empty_and_none_input():
    assert rr.find_stuck([], NOW) == []
    assert rr.find_stuck(None, NOW) == []


def test_custom_threshold():
    got = rr.find_stuck([_run(1, "waiting", 8)], NOW, stuck_minutes=5)
    assert len(got) == 1


# ==================== main（打桩 API） ====================

class _Resp:
    def __init__(self, code, payload):
        self.status = code
        self._code = code
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode() if self._payload is not None else b""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _install(monkeypatch, list_payload, list_code=200, cancel_code=202):
    """打桩 urllib.request.urlopen + 固定当前时间；返回调用记录 dict。"""
    # main() 内部取真实时间，这里固定为 NOW，让「卡死时长」在测试里完全确定
    monkeypatch.setattr(rr, "_now", lambda: NOW)
    calls = {"get": 0, "post": []}

    def _fake(req, timeout=None):
        method = getattr(req, "get_method", lambda: "GET")()
        if method == "GET":
            calls["get"] += 1
            return _Resp(list_code, list_payload)
        calls["post"].append(req.full_url)
        if cancel_code in (202, 204):
            return _Resp(cancel_code, None)
        import urllib.error
        raise urllib.error.HTTPError(req.full_url, cancel_code, "err", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", _fake)
    return calls


def test_main_no_token_returns_zero(monkeypatch):
    """无 token 时静默跳过（本地运行 / 未注入 secrets）。"""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert rr.main() == 0


def test_main_list_failure_returns_zero(monkeypatch):
    """拉取失败也不 fail —— 看门狗自己不该把仓库弄红。"""
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    _install(monkeypatch, {}, list_code=500)
    assert rr.main() == 0


def test_main_cancels_stuck_only(monkeypatch):
    """只取消 waiting/queued 的卡死 run，in_progress 一个都不动。"""
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    payload = {"workflow_runs": [
        _run(111, "waiting", 720),      # 卡死 → cancel
        _run(222, "in_progress", 720),  # 不动
        _run(333, "queued", 60),        # 卡死 → cancel
        _run(444, "completed", 720),    # 不动
    ]}
    calls = _install(monkeypatch, payload)
    assert rr.main() == 0
    assert len(calls["post"]) == 2
    assert any("/111/cancel" in u for u in calls["post"])
    assert any("/333/cancel" in u for u in calls["post"])
    assert not any("/222/cancel" in u for u in calls["post"])
    assert not any("/444/cancel" in u for u in calls["post"])


def test_main_respects_max_cancel(monkeypatch):
    """批量异常时不打爆 API，最多取消 MAX_CANCEL 个。"""
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    monkeypatch.setattr(rr, "MAX_CANCEL", 2)
    payload = {"workflow_runs": [_run(i, "waiting", 100) for i in range(1, 7)]}
    calls = _install(monkeypatch, payload)
    rr.main()
    assert len(calls["post"]) == 2


def test_main_cancel_failure_tolerated(monkeypatch):
    """取消失败（如 409 已失效）不算错误，继续跑完。"""
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    payload = {"workflow_runs": [_run(1, "waiting", 100)]}
    _install(monkeypatch, payload, cancel_code=409)
    assert rr.main() == 0


def test_main_no_stuck_returns_zero(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    payload = {"workflow_runs": [_run(1, "completed", 100)]}
    calls = _install(monkeypatch, payload)
    assert rr.main() == 0
    assert calls["post"] == []
