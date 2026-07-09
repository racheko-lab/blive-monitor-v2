"""notify_dedup 单元测试：去重账本的冷却 / 永久 / 裁剪逻辑。"""
import pytest

import notify_dedup as nd


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """把账本文件指向临时文件，避免污染仓库。"""
    p = tmp_path / "notify_dedup.json"
    monkeypatch.setattr(nd, "LEDGER_FILE", str(p))
    return p


def test_unrecorded_key_allowed(ledger):
    assert nd.should_notify("live:bilibili:123") is True


def test_record_then_suppressed_within_cooldown(ledger):
    key = "live:bilibili:123"
    nd.record(key, now=1000.0)
    # 冷却期内（默认 7200s）应被抑制
    assert nd.should_notify(key, now=1000.0 + 100) is False
    assert nd.should_notify(key, now=1000.0 + nd.LIVE_COOLDOWN_SECONDS - 1) is False


def test_allowed_after_cooldown(ledger):
    key = "live:bilibili:123"
    nd.record(key, now=1000.0)
    assert nd.should_notify(key, now=1000.0 + nd.LIVE_COOLDOWN_SECONDS) is True
    assert nd.should_notify(key, now=1000.0 + nd.LIVE_COOLDOWN_SECONDS + 10) is True


def test_permanent_mode_never_resends(ledger):
    key = "post:MS4wxxx:7490000000000000000"
    nd.record(key, now=1000.0)
    # cooldown=inf：永久不重复
    assert nd.should_notify(key, cooldown=float("inf"), now=1000.0) is False
    assert nd.should_notify(key, cooldown=float("inf"), now=1000.0 + 10**9) is False


def test_count_mode_permanent(ledger):
    key = "post:MS4wxxx:count:42"
    nd.record(key, now=0.0)
    assert nd.should_notify(key, cooldown=float("inf"), now=999999.0) is False


def test_empty_key_always_allowed(ledger):
    assert nd.should_notify("") is True


def test_prune_drops_expired_live_keeps_post(ledger):
    now = 1_000_000.0
    # 一个已过期的 live key
    nd.record("live:bilibili:old", now=now - nd.LIVE_KEY_TTL_SECONDS - 10)
    # 一个未过期的 live key
    nd.record("live:bilibili:fresh", now=now - 100)
    # 一个永久保留的 post key
    nd.record("post:MS4wxxx:abc", now=now - 10)

    nd.prune(now=now)

    ledger = nd._load()
    assert "live:bilibili:old" not in ledger
    assert "live:bilibili:fresh" in ledger
    assert "post:MS4wxxx:abc" in ledger


def test_corrupt_ledger_treated_as_allowed(ledger):
    # 写入损坏的 JSON
    ledger.write_text("{not valid json", encoding="utf-8")
    # 不应抛异常，且视为未记录 → 允许推送
    assert nd.should_notify("live:x:1") is True
