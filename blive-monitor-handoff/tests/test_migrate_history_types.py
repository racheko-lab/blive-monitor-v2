"""migrate_history_types 单元测试：status→type 推导、level 回填、幂等。"""
import importlib.util
import json
import os

# 以文件方式加载 tools/migrate_history_types.py（与 test_merge_state 同款手法）
_spec = importlib.util.spec_from_file_location(
    "migrate_history_types",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tools", "migrate_history_types.py",
    ),
)
mht = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mht)


def test_backfill_status_to_type():
    assert mht.backfill_type({"status": "live"})["type"] == "live_on"
    assert mht.backfill_type({"status": "offline"})["type"] == "live_off"
    assert mht.backfill_type({"status": "replay"})["type"] == "live_off"
    assert mht.backfill_type({"status": "error"})["type"] == "error"
    assert mht.backfill_type({"status": "unknown"})["type"] == "system"
    assert mht.backfill_type({})["type"] == "system"


def test_backfill_level_derived():
    assert mht.backfill_type({"status": "error"})["level"] == "error"
    assert mht.backfill_type({"status": "live"})["level"] == "info"
    assert mht.backfill_type({"status": "offline"})["level"] == "info"


def test_backfill_does_not_overwrite_existing_type():
    e = {"status": "live", "type": "system"}
    mht.backfill_type(e)
    assert e["type"] == "system"  # 已存在不覆盖


def test_run_idempotent(tmp_path):
    p = tmp_path / "history.json"
    data = [
        {"time": "2026-07-10 10:00", "name": "A", "status": "live"},
        {"time": "2026-07-10 10:01", "name": "B", "status": "offline"},
        {"time": "2026-07-10 10:02", "name": "C", "status": "error"},
        {"time": "2026-07-10 10:03", "name": "D", "status": "replay"},
        {"time": "2026-07-10 10:04", "name": "E"},  # 无 status → system
    ]
    p.write_text(json.dumps(data), encoding="utf-8")
    n1 = mht.run(str(p))
    assert n1 == 5
    hist1 = json.loads(p.read_text(encoding="utf-8"))
    assert all("type" in e for e in hist1)
    assert all("level" in e for e in hist1)
    # 重跑：不应再补写
    n2 = mht.run(str(p))
    assert n2 == 0
    # 条数不变
    hist2 = json.loads(p.read_text(encoding="utf-8"))
    assert len(hist2) == 5
    assert hist2[0]["type"] == "live_on"
    assert hist2[2]["type"] == "error"
    assert hist2[4]["type"] == "system"


def test_run_dry_run_does_not_modify(tmp_path):
    p = tmp_path / "history.json"
    p.write_text(json.dumps([{"status": "live"}]), encoding="utf-8")
    mht.run(str(p), dry_run=True)
    # 文件未变（仍无 type）
    hist = json.loads(p.read_text(encoding="utf-8"))
    assert "type" not in hist[0]
