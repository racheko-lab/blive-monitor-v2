"""阶段四后端 REST API 测试（核心路径）。

用 fastapi.testclient.TestClient 对 ``backend.app:app`` 做端到端验证：
  - /healthz（鉴权豁免）
  - rooms 增删改查（含 status 读写）
  - /config GET/PUT 兼容往返（BLIVE_CONFIG）
  - /summary/state、/silence/state 读写
  - AUTH_TOKEN 设值时写接口返回 401（读接口 / /healthz 豁免）

每个用例用临时 SQLite 隔离（monkeypatch engine）。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.db as dbmod
from backend import app as app_module


def _tmp_engine(tmp_path, monkeypatch):
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
    return eng


@pytest.fixture
def client(tmp_path, monkeypatch):
    _tmp_engine(tmp_path, monkeypatch)
    # 默认无鉴权（内网语义）。
    monkeypatch.setattr("backend.config.AUTH_TOKEN", "")
    yield TestClient(app_module.app)


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    _tmp_engine(tmp_path, monkeypatch)
    monkeypatch.setattr("backend.config.AUTH_TOKEN", "secret-token")
    yield TestClient(app_module.app)


# ==================== /healthz ====================
def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ==================== rooms CRUD ====================
def test_rooms_lifecycle(client):
    # create
    r = client.post(
        "/api/v1/rooms",
        json={"platform": "bilibili", "external_id": "22230707", "kind": "live", "name": "测试"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] > 0
    rid = body["id"]

    # list
    lst = client.get("/api/v1/rooms")
    assert lst.status_code == 200
    assert lst.json()["total"] == 1
    assert lst.json()["items"][0]["external_id"] == "22230707"

    # get one
    one = client.get(f"/api/v1/rooms/{rid}")
    assert one.status_code == 200
    assert one.json()["name"] == "测试"

    # update
    upd = client.put(f"/api/v1/rooms/{rid}", json={"name": "改名", "enabled": False})
    assert upd.status_code == 200
    assert upd.json()["name"] == "改名"
    assert upd.json()["enabled"] is False

    # status read/write
    st = client.put(
        f"/api/v1/rooms/{rid}/status",
        json={"live_status": "live", "online": 3, "area": "游戏", "title": "T"},
    )
    assert st.status_code == 200
    assert st.json()["live_status"] == "live"
    assert st.json()["online"] == 3
    st_get = client.get(f"/api/v1/rooms/{rid}/status")
    assert st_get.json()["live_status"] == "live"

    # delete
    d = client.delete(f"/api/v1/rooms/{rid}")
    assert d.status_code == 204
    assert client.get(f"/api/v1/rooms/{rid}").status_code == 404


def test_rooms_unknown_404(client):
    assert client.get("/api/v1/rooms/999999").status_code == 404
    assert client.delete("/api/v1/rooms/999999").status_code == 404


# ==================== /config 兼容往返 ====================
SAMPLE_CONFIG = {
    "channels": [{"id": "wecom", "type": "wecom", "webhook": "https://example"}],
    "routes": [{"tag": None, "channel": "wecom"}],
    "templates": {"live_on": {"title": "开播", "desp": "主播开播了"}},
    "silence": {"enabled": False, "start": "23:00", "end": "08:00"},
    "summary": {"enabled": False, "freq": "daily", "sendTime": "09:00"},
    "push": {},
    "platforms": {},
}


def test_config_roundtrip(client):
    # 默认返回含空段的可用配置。
    g0 = client.get("/api/v1/config")
    assert g0.status_code == 200
    assert "channels" in g0.json()

    # PUT 后 GET 应原样返回（兼容 BLIVE_CONFIG 语义）。
    put = client.put("/api/v1/config", json=SAMPLE_CONFIG)
    assert put.status_code == 200
    assert "updated_at" in put.json()

    g1 = client.get("/api/v1/config")
    assert g1.status_code == 200
    assert g1.json() == SAMPLE_CONFIG


# ==================== summary / silence state ====================
def test_summary_state_rw(client):
    g = client.get("/api/v1/summary/state")
    assert g.status_code == 200
    assert g.json()["enabled"] is False

    p = client.put("/api/v1/summary/state", json={"enabled": True, "sendTime": "10:00"})
    assert p.status_code == 200
    body = p.json()
    assert body["enabled"] is True
    assert body["sendTime"] == "10:00"

    # 再次 GET 应反映最新值。
    assert client.get("/api/v1/summary/state").json()["enabled"] is True


def test_silence_state_rw(client):
    g = client.get("/api/v1/silence/state")
    assert g.status_code == 200
    p = client.put("/api/v1/silence/state", json={"enabled": True, "start": "22:00", "end": "07:00"})
    assert p.status_code == 200
    assert p.json()["enabled"] is True
    assert p.json()["start"] == "22:00"


# ==================== 鉴权 ====================
def test_auth_requires_token(auth_client):
    r = auth_client.put("/api/v1/config", json=SAMPLE_CONFIG)
    assert r.status_code == 401


def test_auth_with_token_ok(auth_client):
    r = auth_client.put(
        "/api/v1/config", json=SAMPLE_CONFIG, headers={"X-Bearer-Token": "secret-token"}
    )
    assert r.status_code == 200


def test_auth_read_exempt(auth_client):
    # 读接口与 /healthz 豁免鉴权。
    assert auth_client.get("/api/v1/config").status_code == 200
    assert auth_client.get("/api/v1/summary/state").status_code == 200
    assert auth_client.get("/healthz").status_code == 200


def test_auth_disabled_allows_write(client):
    # AUTH_TOKEN 为空时放行写接口。
    assert client.put("/api/v1/config", json=SAMPLE_CONFIG).status_code == 200
