"""阶段四迁移脚本测试（幂等导入）。

在临时仓库目录造 mini JSON fixtures，运行 ``tools/import_json_to_db.py`` 对临时 SQLite
做幂等导入，断言落库行数正确（rooms=2 / posts=1 / events=1 / notify_dedup=1），并重跑
验证幂等（行数稳定）。
"""

import importlib.util
import json
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend
import backend.db as dbmod
from backend.core.dedup import DedupService
from backend.core.persistence import Persistence


REPO_ROOT = os.path.dirname(os.path.dirname(backend.__file__))
SCRIPT_PATH = os.path.join(REPO_ROOT, "tools", "import_json_to_db.py")


def _load_importer():
    spec = importlib.util.spec_from_file_location("phase4_import_json", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def migration_env(tmp_path, monkeypatch):
    """临时仓库（含样例 JSON）+ 临时 SQLite（monkeypatch engine）。"""
    repo = tmp_path / "repo"
    repo.mkdir()

    (repo / "rooms.json").write_text(json.dumps(
        [{"platform": "bilibili", "id": "22230707", "name": "测试直播"}]
    ), encoding="utf-8")
    (repo / "status.json").write_text(json.dumps({
        "updated": "2024-01-01 00:00:00",
        "rooms": [{
            "platform": "bilibili", "id": "22230707", "status": "live",
            "title": "T", "online": 10, "area": "游戏", "time": "2024-01-01 00:00:00",
            "last_live": "2024-01-01 00:00:00", "live_duration": "1h", "sec_uid": "",
        }],
    }), encoding="utf-8")
    (repo / "state.json").write_text(json.dumps(
        {"bilibili_22230707": "live"}
    ), encoding="utf-8")
    (repo / "tracking.json").write_text(json.dumps({
        "bilibili_22230707": {"last_live": "2024-01-01 00:00:00", "live_duration": "1h"},
    }), encoding="utf-8")
    (repo / "post_rooms.json").write_text(json.dumps(
        [{"id": "601914453", "name": "抖音号", "sec_uid": "abc"}]
    ), encoding="utf-8")
    (repo / "post_tracking.json").write_text(json.dumps({
        "douyin_601914453": {
            "sec_uid": "abc", "latest_aweme_id": "12345", "nickname": "抖音号",
            "latest_url": "http://x", "latest_cover": "http://c",
        },
    }), encoding="utf-8")
    (repo / "history.json").write_text(json.dumps([{
        "time": "2024-01-01 00:00:00", "rid": "bilibili_22230707",
        "account": "bilibili_22230707", "name": "测试直播", "platform": "bilibili",
        "status": "live", "title": "T", "type": "live_on", "changed": True,
        "prev": "offline", "push": "pushed_ok", "level": "info",
    }]), encoding="utf-8")
    (repo / "notify_dedup.json").write_text(json.dumps({
        "live:bilibili_22230707": {"ts": 1700000000.0},
    }), encoding="utf-8")
    (repo / "summary_state.json").write_text(json.dumps(
        {"enabled": False, "freq": "daily", "sendTime": "09:00", "lastSent": 0}
    ), encoding="utf-8")
    (repo / "silence_state.json").write_text(json.dumps(
        {"enabled": False, "start": "23:00", "end": "08:00"}
    ), encoding="utf-8")

    db_file = tmp_path / "blive.db"
    monkeypatch.setenv("BLIVE_DB_PATH", str(db_file))
    eng = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    monkeypatch.setattr(dbmod, "engine", eng)
    monkeypatch.setattr(
        dbmod, "SessionLocal", sessionmaker(bind=eng, expire_on_commit=False, future=True)
    )
    import backend.models  # noqa: F401

    dbmod.Base.metadata.create_all(eng)

    yield str(repo), str(db_file)


def _run(imp, repo, db_file, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["import_json_to_db.py", "--repo-root", repo, "--db", db_file]
    )
    return imp.main()


def test_migration_idempotent(migration_env, monkeypatch):
    repo, db_file = migration_env
    imp = _load_importer()

    rc = _run(imp, repo, db_file, monkeypatch)
    assert rc == 0

    pers = Persistence()
    dedup = DedupService()

    # rooms: 1 live + 1 post = 2
    assert pers.count_rooms() == 2
    assert pers.count_rooms(kind="live") == 1
    assert pers.count_rooms(kind="post") == 1
    # posts: latest_aweme_id 种子 1 条
    assert pers.count_posts() == 1
    # events_history: 1 条
    assert pers.count_events() == 1
    # notify_dedup: 1 条，且时间戳已记录
    assert dedup.last_sent_at("live:bilibili_22230707") > 0

    # 幂等重跑：行数稳定（events_history 清空+重插仍 1 条）。
    rc2 = _run(imp, repo, db_file, monkeypatch)
    assert rc2 == 0
    assert pers.count_rooms() == 2
    assert pers.count_posts() == 1
    assert pers.count_events() == 1
    assert dedup.last_sent_at("live:bilibili_22230707") > 0
