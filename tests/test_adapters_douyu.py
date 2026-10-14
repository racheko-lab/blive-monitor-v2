"""DouyuAdapter / fetch_douyu 单测（阶段：斗鱼直播监控接入）。

全部用例对网络层打桩（monkeypatch ``_http_get_json``），不依赖外网，
保证在 GitHub Actions 无网/限网环境下也稳定可跑。

真实接口形态（2026-10-02 沙箱实测，仅作打桩数据依据）:
    {"error":0,"data":{"room_id":"36252","room_name":"Gemini：AG VS Hero",
     "room_status":"1","owner_name":"MrGemini","online":5622051,
     "cate_name":"王者荣耀","avatar":"...","room_thumb":"...",
     "start_time":"2026-10-02 13:25:13"}}
    异常：/room/0 -> {"error":101,"data":"房间未找到"}
          /room/999999999 -> 纯文本 "Not Found"（非 JSON）
"""

import json
import pytest

from backend.adapters.base import AdapterError
from backend.adapters.douyu import DouyuAdapter

# 真实响应精简样本（去掉庞大的 gift 数组）
LIVE_PAYLOAD = {
    "error": 0,
    "data": {
        "room_id": "36252",
        "room_name": "Gemini：AG VS Hero",
        "room_status": "1",
        "owner_name": "MrGemini",
        "online": 5622051,
        "cate_name": "王者荣耀",
        "avatar": "https://apic.douyucdn.cn/upload/avatar_v3/xxx_big.jpg",
        "room_thumb": "https://rpic.douyucdn.cn/live-cover/xxx.jpg/dy1",
        "start_time": "2026-10-02 13:25:13",
    },
}
OFFLINE_PAYLOAD = {
    "error": 0,
    "data": {
        "room_id": "15000",
        "room_name": "用户已注销的直播间 15000",
        "room_status": "0",
        "owner_name": "用户已注销",
        "online": 0,
        "cate_name": "英雄联盟",
        "avatar": "https://apic.douyucdn.cn/upload/avatar/default/07_big.jpg",
        "room_thumb": "https://rpic.douyucdn.cn/default2.gif/dy1",
        "start_time": "1970-01-01 08:00:00",
    },
}


@pytest.fixture
def adapter(monkeypatch):
    """返回已打桩网络层的 DouyuAdapter，payload 可通过 ``set_payload`` 换。"""
    ad = DouyuAdapter()

    def set_payload(obj):
        monkeypatch.setattr(ad, "_http_get_json", lambda url, timeout=10: obj)

    ad.set_payload = set_payload  # type: ignore[attr-defined]
    return ad


def test_live_room_maps_all_fields(adapter):
    """直播中房间：状态/标题/昵称/人气/分区/头像/封面/URL 逐字段映射。"""
    adapter.set_payload(LIVE_PAYLOAD)
    m = adapter.fetch_room_status("36252")
    assert m.platform == "douyu"
    assert m.room_id == "36252"
    assert m.live_status is True
    assert m.title == "Gemini：AG VS Hero"
    assert m.name == "MrGemini"
    assert m.online == 5622051
    assert m.area == "王者荣耀"
    assert m.avatar.endswith("_big.jpg")
    assert m.cover.endswith("/dy1")
    assert m.url == "https://www.douyu.com/36252"
    assert m.extra["room_status_raw"] == "1"
    assert m.extra["start_time"] == "2026-10-02 13:25:13"


def test_offline_room(adapter):
    """未开播房间：live_status=False，其余字段照常映射。"""
    adapter.set_payload(OFFLINE_PAYLOAD)
    m = adapter.fetch_room_status("15000")
    assert m.live_status is False
    assert m.name == "用户已注销"
    assert m.area == "英雄联盟"
    assert m.online == 0


def test_room_not_found_raises(adapter):
    """error!=0（房间不存在）必须抛错，不能静默当 offline——否则失效房间会被伪装成「未开播」。

    注：非 JSON 响应（如超大房间号返回纯文本 "Not Found"）由 ``_http_get_json``
    转成 AdapterError，同样不会静默降级。
    """
    adapter.set_payload({"error": 101, "data": "房间未找到"})
    with pytest.raises(AdapterError):
        adapter.fetch_room_status("0")


def test_empty_data_raises(adapter):
    """data 缺失/空 dict 视为不可用，抛错而非返回空 RoomModel。"""
    adapter.set_payload({"error": 0, "data": {}})
    with pytest.raises(AdapterError):
        adapter.fetch_room_status("15000")


@pytest.mark.parametrize("rid", ["", "abc", "15 000", "-1", "1.5", "房间号"])
def test_non_numeric_rid_raises(adapter, rid):
    """斗鱼房间号必须为纯数字：非法输入本地即拒绝，不浪费一次网络往返。"""
    with pytest.raises(AdapterError):
        adapter.fetch_room_status(rid)


def test_batch_skips_failed_rooms(adapter, monkeypatch):
    """批量查询：单房失败不影响其余房间，失败项不进返回 dict。"""
    calls = []

    def fake(url, timeout=10):
        calls.append(url)
        if "36252" in url:
            return LIVE_PAYLOAD
        return {"error": 101, "data": "房间未找到"}

    monkeypatch.setattr(adapter, "_http_get_json", fake)
    out = adapter.fetch_room_status_batch(["36252", "0"])
    assert list(out.keys()) == ["36252"]
    assert out["36252"].live_status is True
    assert len(calls) == 2  # 两间都发了请求，失败的被跳过而非中断


def test_posts_not_supported(adapter):
    """斗鱼无「新作品」形态：fetch_new_posts 显式抛 NotImplementedError 防误用。"""
    assert adapter.supports_posts is False
    with pytest.raises(NotImplementedError):
        adapter.fetch_new_posts("36252")


def test_http_get_json_rejects_non_json(monkeypatch):
    """/room/999999999 返回纯文本 "Not Found" —— 必须转成 AdapterError。"""
    import urllib.request
    import io

    class FakeResp:
        def read(self):
            return b"Not Found"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda req, timeout=None: FakeResp()
    )
    with pytest.raises(AdapterError):
        DouyuAdapter()._http_get_json("https://open.douyucdn.cn/api/RoomApi/room/999999999")


def test_fetch_douyu_wrapper_live(monkeypatch):
    """check_status.fetch_douyu：正常路径 → status=live，带 nickname/avatar。"""
    import check_status

    monkeypatch.setattr(
        DouyuAdapter, "fetch_room_status", lambda self, rid: _model_from(LIVE_PAYLOAD["data"])
    )
    r = check_status.fetch_douyu("36252")
    assert r["status"] == "live"
    assert r["title"] == "Gemini：AG VS Hero"
    assert r["nickname"] == "MrGemini"
    assert r["area"] == "王者荣耀"
    assert r["online"] == 5622051
    assert r["avatar"].endswith("_big.jpg")


def test_fetch_douyu_wrapper_error_degrades_to_error(monkeypatch):
    """异常路径 → status=error（与 bili/douyin/kuaishou 一致），不静默 offline。"""
    import check_status

    def boom(self, rid):
        raise AdapterError("斗鱼房间不可用: error=101 房间未找到")

    monkeypatch.setattr(DouyuAdapter, "fetch_room_status", boom)
    r = check_status.fetch_douyu("0")
    assert r["status"] == "error"
    assert "获取失败" in r["title"]


def test_douyu_push_text_has_label_and_url():
    """推送文案：平台标签「斗鱼」+ 直播间 URL 走 www.douyu.com/{rid}。"""
    import check_status

    desp = check_status.format_push_desp(
        "MrGemini",
        "douyu",
        "36252",
        {"status": "live", "title": "Gemini：AG VS Hero", "online": 5622051, "area": "王者荣耀"},
    )
    assert "**平台**: 斗鱼" in desp
    assert "https://www.douyu.com/36252" in desp
    assert "**分区**: 王者荣耀" in desp

    body = check_status.render_body(
        {"name": "MrGemini", "platform": "douyu", "rid": "36252", "result": {"status": "live"}},
        "live_on",
        {"templates": {"live_on": "{name} 开播 {url} {platform}"}},
    )
    assert body == "MrGemini 开播 https://www.douyu.com/36252 douyu"


# ==================== 房间「靓号」解析 ====================
# 斗鱼给主播分配短号（如 15000），访问 m.douyu.com/15000 会渲染出真实房间的直播间。
# 但公开接口 RoomApi 只认真实房间 ID（796449），传靓号会返回一个「已注销」样式的占位壳，
# 不解析就会把一个正在直播的房间误判成废号。

PRETTY_PLACEHOLDER = {
    "error": 0,
    "data": {
        "room_id": "15000",
        "room_name": "用户已注销的直播间 15000",
        "room_status": "0",
        "owner_name": "用户已注销",
        "online": 0,
        "cate_name": "英雄联盟",
        "avatar": "https://apic.douyucdn.cn/upload/avatar/default/07_big.jpg",
        "room_thumb": "https://rpic.douyucdn.cn/default2.gif/dy1",
        "start_time": "1970-01-01 08:00:00",
    },
}
# 靓号页面 SSR 片段：roomId 照抄 URL，rid 才是真身
PRETTY_PAGE_HTML = (
    '<script>window.__INIT={"roomId":"15000","rid":796449,'
    '"nickname":"宁波小骚骚0oO"}</script>'
)


def test_pretty_id_placeholder_is_detected():
    """占位壳必须被识别（否则靓号会被当废号静默 offline）。"""
    assert DouyuAdapter._looks_like_pretty_id_placeholder(PRETTY_PLACEHOLDER["data"]) is True
    assert DouyuAdapter._looks_like_pretty_id_placeholder(LIVE_PAYLOAD["data"]) is False
    assert DouyuAdapter._looks_like_pretty_id_placeholder(None) is False


def test_pretty_id_resolved_to_real_room(monkeypatch):
    """靓号 15000：占位壳 → 页面解析出 796449 → 重查拿到真实开播态。

    room_id 保留靓号（URL 用靓号，点进去由斗鱼跳转），真实房间号放 extra。
    """
    ad = DouyuAdapter()
    calls = []

    def fake_json(url, timeout=10):
        calls.append(url)
        return PRETTY_PLACEHOLDER if "/15000" in url else LIVE_PAYLOAD

    monkeypatch.setattr(ad, "_http_get_json", fake_json)
    monkeypatch.setattr(ad, "_resolve_pretty_id", lambda pid, timeout=10: "796449")

    m = ad.fetch_room_status("15000")
    assert m.live_status is True
    assert m.name == "MrGemini"          # 来自真实房间 796449 的数据
    assert m.room_id == "15000"          # 房间号保留靓号
    assert m.url == "https://www.douyu.com/15000"
    assert m.extra["resolved_room_id"] == "796449"
    assert m.extra["is_pretty_id"] is True
    # 两次请求：一次靓号（拿到占位壳）+ 一次真实房间
    assert len(calls) == 2


def test_pretty_id_unresolvable_raises(monkeypatch):
    """占位壳 + 解析无结果 = 真废号，必须报错而不是静默 offline。"""
    ad = DouyuAdapter()
    monkeypatch.setattr(ad, "_http_get_json", lambda url, timeout=10: PRETTY_PLACEHOLDER)
    monkeypatch.setattr(ad, "_resolve_pretty_id", lambda pid, timeout=10: None)
    with pytest.raises(AdapterError):
        ad.fetch_room_status("15000")


def test_pretty_id_page_returns_same_id_raises(monkeypatch):
    """页面解析回同一个号（说明不是靓号，就是废号）→ 报错。"""
    ad = DouyuAdapter()
    monkeypatch.setattr(ad, "_http_get_json", lambda url, timeout=10: PRETTY_PLACEHOLDER)
    monkeypatch.setattr(ad, "_resolve_pretty_id", lambda pid, timeout=10: "15000")
    with pytest.raises(AdapterError):
        ad.fetch_room_status("15000")


def test_normal_room_does_not_trigger_pretty_resolution(monkeypatch):
    """正常房间不得触发靓号解析（省掉一次 135KB 的页面请求）。"""
    ad = DouyuAdapter()
    monkeypatch.setattr(ad, "_http_get_json", lambda url, timeout=10: LIVE_PAYLOAD)

    def boom(pid, timeout=10):
        raise AssertionError("正常房间不应走靓号解析")

    monkeypatch.setattr(ad, "_resolve_pretty_id", boom)
    m = ad.fetch_room_status("796449")
    assert m.live_status is True
    assert "is_pretty_id" not in m.extra


def test_resolve_pretty_id_extracts_rid_not_room_id(monkeypatch):
    """页面里必须取 `"rid"`，不能取 `"roomId"`（后者只是照抄 URL）。"""
    ad = DouyuAdapter()
    import urllib.request

    class FakeResp:
        def read(self):
            return PRETTY_PAGE_HTML.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeResp())
    assert ad._resolve_pretty_id("15000") == "796449"


def _model_from(data):
    """把打桩 data 转成 RoomModel（与适配器同一套映射规则）。"""
    from backend.adapters.base import RoomModel

    return RoomModel(
        platform="douyu",
        room_id=str(data.get("room_id") or ""),
        name=str(data.get("owner_name") or ""),
        title=str(data.get("room_name") or ""),
        live_status=str(data.get("room_status") or "") == "1",
        url=f"https://www.douyu.com/{data.get('room_id')}",
        cover=str(data.get("room_thumb") or ""),
        avatar=str(data.get("avatar") or ""),
        online=int(data.get("online") or 0),
        area=str(data.get("cate_name") or ""),
        extra={"room_status_raw": str(data.get("room_status") or "")},
    )
