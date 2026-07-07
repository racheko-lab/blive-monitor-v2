"""check_new_posts 单元测试：导入可行性、模块复用 common、新作品基线判定（纯函数）。"""
import json
import sys
import types

import pytest

import check_new_posts as cnp


# ---------- 假 Playwright：让 main() 的惰性 import 可用，无需真实浏览器 ----------
class _FakeContext:
    def close(self):
        pass


class _FakeBrowser:
    def new_context(self, **kwargs):
        return _FakeContext()

    def close(self):
        pass


class _FakePW:
    def __init__(self):
        self.chromium = types.SimpleNamespace(launch=lambda **kw: _FakeBrowser())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_fake_playwright():
    """注入假的 playwright.sync_api 模块，使 main() 的 `from playwright... import` 成功。"""
    if "playwright" not in sys.modules:
        sys.modules["playwright"] = types.ModuleType("playwright")
    fake = types.ModuleType("playwright.sync_api")
    fake.sync_playwright = lambda: _FakePW()
    sys.modules["playwright.sync_api"] = fake


def test_module_imports_common():
    # 复用 common 的 bjnow / load_json_file / save_json_file
    assert hasattr(cnp, "bjnow")
    assert hasattr(cnp, "load_json_file")
    assert hasattr(cnp, "save_json_file")


def test_push_utils_imported():
    assert hasattr(cnp, "dispatch_push")
    assert hasattr(cnp, "load_push_cfg")


@pytest.mark.parametrize("prev_id,prev_ct,new_id,new_ct,expected", [
    ("old", 100, "new", 200, True),     # 确实更新 -> 通知
    ("old", 100, "new", 50, False),     # 接口返回更旧 -> 不误报
    ("same", 100, "same", 200, False),  # 同一作品 -> 不重复通知
    ("", 0, "new", 200, False),         # 首次仅建立基线，不推送（避免启用即轰炸）
    ("old", 100, "new", 100, False),    # 相同时间戳不同 id -> 不通知
])
def test_should_notify_new_post(prev_id, prev_ct, new_id, new_ct, expected):
    assert cnp.should_notify_new_post(prev_id, prev_ct, new_id, new_ct) is expected


@pytest.mark.parametrize("prev_id,prev_ct,new_id,new_ct,expected", [
    ("old", 100, "new", 200, True),   # 更新基线（更新时间戳）
    ("old", 100, "new", 50, False),   # 更旧 -> 保留旧基线（防接口延迟回退）
    ("", 0, "new", 200, True),        # 首次 -> 建立基线
    ("old", 100, "old", 100, True),   # 同一作品 -> 允许重写（无害）
    ("old", 100, "new", 100, False),  # 相同时戳不同 id -> 无法判定更新，保留基线防震荡
])
def test_should_update_baseline(prev_id, prev_ct, new_id, new_ct, expected):
    assert cnp.should_update_baseline(prev_id, prev_ct, new_id, new_ct) is expected


# ==================== main() 端到端（mock 浏览器，真实走流程） ====================

def _seed(tmp_path, monkeypatch, post_rooms, tracking=None, push_cfg='{"push":{"type":"bark","url":"https://api.day.app/K"}}'):
    config_file = tmp_path / "post_rooms.json"
    config_file.write_text(json.dumps(post_rooms), encoding="utf-8")
    tracking_file = tmp_path / "post_tracking.json"
    if tracking is not None:
        tracking_file.write_text(json.dumps(tracking), encoding="utf-8")
    monkeypatch.setattr(cnp, "CONFIG_FILE", str(config_file))
    monkeypatch.setattr(cnp, "TRACKING_FILE", str(tracking_file))
    monkeypatch.setattr(cnp, "resolve_sec_uid", lambda ctx, rid: rid)
    monkeypatch.setenv("ENABLE_POST_CHECK", "true")
    monkeypatch.setenv("BLIVE_CONFIG", push_cfg)
    return tracking_file


def test_main_first_run_establishes_baseline_no_notify(tmp_path, monkeypatch):
    """首次运行仅建立基线，不推送（避免启用即轰炸）。"""
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}])
    calls = []
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: {
        "aweme_id": "999", "desc": "新视频", "video_url": "https://v/999",
        "is_note": False, "nickname": "阿伟", "create_time": 1700000000,
    })

    cnp.main()

    tracking = json.loads(tf.read_text(encoding="utf-8"))
    assert tracking["douyin_MS4wABC"]["latest_aweme_id"] == "999"
    assert tracking["douyin_MS4wABC"]["latest_ct"] == 1700000000
    assert calls == []


def test_main_detects_new_post_and_notifies(tmp_path, monkeypatch):
    """基线已知 888，接口取到更新的 999 → 推送一次且更新基线。"""
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
               tracking={"douyin_MS4wABC": {"sec_uid": "MS4wABC", "latest_aweme_id": "888", "latest_ct": 1699999000}})
    calls = []
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: {
        "aweme_id": "999", "desc": "新视频", "video_url": "https://v/999",
        "is_note": False, "nickname": "阿伟", "create_time": 1700000000,
    })

    cnp.main()

    tracking = json.loads(tf.read_text(encoding="utf-8"))
    assert tracking["douyin_MS4wABC"]["latest_aweme_id"] == "999"
    assert len(calls) == 1
    assert "新作品" in calls[0]


def test_main_feed_lag_keeps_baseline(tmp_path, monkeypatch):
    """接口返回的作品反而更旧（feed 延迟）→ 不误推送、也不回退基线。"""
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
               tracking={"douyin_MS4wABC": {"sec_uid": "MS4wABC", "latest_aweme_id": "888", "latest_ct": 1700000000}})
    calls = []
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: {
        "aweme_id": "777", "desc": "旧视频", "video_url": "https://v/777",
        "is_note": False, "nickname": "阿伟", "create_time": 1699999000,
    })

    cnp.main()

    tracking = json.loads(tf.read_text(encoding="utf-8"))
    assert tracking["douyin_MS4wABC"]["latest_aweme_id"] == "888"   # 基线不变
    assert tracking["douyin_MS4wABC"]["latest_ct"] == 1700000000
    assert calls == []


def test_main_cleans_up_removed_accounts(tmp_path, monkeypatch):
    """监控列表已不含某账号 → 其历史状态被清理。"""
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
               tracking={
                   "douyin_MS4wABC": {"sec_uid": "MS4wABC", "latest_aweme_id": "888", "latest_ct": 1},
                   "douyin_OLD123": {"sec_uid": "MS4wOLD", "latest_aweme_id": "1", "latest_ct": 1},
               },
               push_cfg="{}")
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: {
        "aweme_id": "999", "desc": "x", "video_url": "https://v/999",
        "is_note": False, "nickname": "阿伟", "create_time": 1700000000,
    })

    cnp.main()

    tracking = json.loads(tf.read_text(encoding="utf-8"))
    assert "douyin_MS4wABC" in tracking
    assert "douyin_OLD123" not in tracking


# ==================== 多策略解析 / Cookie 逻辑 ====================

POPULATED = {
    "status_code": 0,
    "aweme_list": [
        {"aweme_id": "777", "desc": "旧", "create_time": 100, "author": {"nickname": "阿伟"}},
        {"aweme_id": "999", "desc": "新视频", "create_time": 200, "author": {"nickname": "阿伟"}, "video": {"play_addr": {}}},
        {"aweme_id": "888", "desc": "图文", "create_time": 150, "images": [{"url": "x"}]},
    ],
    "has_more": 1,
}


def test_parse_aweme_list_populated():
    items = cnp.parse_aweme_list(json.dumps(POPULATED))
    assert len(items) == 3
    # 最新按 (create_time, aweme_id) 取最大
    latest = max(items, key=cnp._sort_key)
    assert latest["aweme_id"] == "999"
    assert latest["is_note"] is False
    assert latest["video_url"] == "https://www.douyin.com/video/999"
    note = next(i for i in items if i["aweme_id"] == "888")
    assert note["is_note"] is True
    assert note["video_url"] == "https://www.douyin.com/note/888"


def test_parse_aweme_list_gated():
    # 风控：status_code 非 0 且无列表 -> 空
    assert cnp.parse_aweme_list(json.dumps({"status_code": 2151, "aweme_list": []})) == []
    # 空体
    assert cnp.parse_aweme_list("") == []
    # 损坏 JSON
    assert cnp.parse_aweme_list("{bad") == []


def test_parse_aweme_count():
    assert cnp.parse_aweme_count(json.dumps({"user": {"aweme_count": 42}})) == 42
    assert cnp.parse_aweme_count(json.dumps({"data": {"user": {"aweme_count": 7}}})) == 7
    assert cnp.parse_aweme_count("") is None
    assert cnp.parse_aweme_count(json.dumps({"user": {}})) is None


class FakeResp:
    def __init__(self, url, body):
        self.url = url
        self._body = body

    def body(self):
        return self._body.encode("utf-8")


class FakePage:
    def __init__(self, responses=None):
        self._handlers = []
        self._responses = responses or []
        self.closed = False

    def on(self, event, handler):
        if event == "response":
            self._handlers.append(handler)

    def goto(self, url, **kw):
        for u, b in self._responses:
            for h in self._handlers:
                h(FakeResp(u, b))

    def wait_for_timeout(self, ms):
        pass

    def close(self):
        self.closed = True


class FakeCtx:
    def __init__(self, page):
        self._page = page
        self.cookies = []

    def new_page(self):
        return self._page

    def add_cookies(self, cookies):
        self.cookies.extend(cookies)

    def close(self):
        pass


def test_get_latest_aweme_strategy1_api():
    page = FakePage(responses=[("https://www.douyin.com/aweme/v1/web/aweme/post/?x=1", json.dumps(POPULATED))])
    res = cnp.get_latest_aweme(FakeCtx(page), "MS4wSEC")
    assert res is not None
    assert res["aweme_id"] == "999"


def test_get_latest_aweme_strategy1_api_has_conf():
    page = FakePage(responses=[("https://www.douyin.com/aweme/v1/web/aweme/post/?x=1", json.dumps(POPULATED))])
    res = cnp.get_latest_aweme(FakeCtx(page), "MS4wSEC")
    assert res is not None
    assert res["aweme_id"] == "999"
    assert res["_conf"] == "api"  # 真实接口，置信度高


def test_get_latest_aweme_strategy2_count():
    """无 Cookie 时退化为按作品数推测（user/profile/other 未登录仍返回真实总数）。"""
    page = FakePage(
        responses=[
            ("https://www.douyin.com/aweme/v1/web/aweme/post/?x=1", ""),
            ("https://www.douyin.com/aweme/v1/web/user/profile/other?x=2", json.dumps({"user": {"aweme_count": 12}})),
        ],
    )
    res = cnp.get_latest_aweme(FakeCtx(page), "MS4wSEC")
    assert res is not None
    assert res["aweme_id"] == "count:12"
    assert res["_conf"] == "count"
    assert res["video_url"] == "https://www.douyin.com/user/MS4wSEC"


def test_get_latest_aweme_gated_returns_none():
    page = FakePage(
        responses=[
            ("https://www.douyin.com/aweme/v1/web/aweme/post/?x=1", ""),
            ("https://www.douyin.com/aweme/v1/web/user/profile/other?x=2", ""),
        ],
    )
    assert cnp.get_latest_aweme(FakeCtx(page), "MS4wSEC") is None


def _count_aweme(n):
    return {
        "aweme_id": f"count:{n}", "desc": "", "video_url": "https://u/xxx",
        "is_note": False, "nickname": "", "create_time": n, "_conf": "count",
    }


def _api_aweme(aid, ct):
    return {
        "aweme_id": str(aid), "desc": "x", "video_url": f"https://v/{aid}",
        "is_note": False, "nickname": "阿伟", "create_time": ct, "_conf": "api",
    }


def test_main_count_mode_speculates(tmp_path, monkeypatch):
    """count 模式：作品数 10→12 增加时，推测「可能有新作品」并带主页链接。"""
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
               tracking={"douyin_MS4wABC": {"sec_uid": "MS4wABC", "mode": "count",
                                            "latest_aweme_id": "count:10", "latest_ct": 10, "latest_count": 10}})
    calls = []
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: _count_aweme(12))

    cnp.main()

    tracking = json.loads(tf.read_text(encoding="utf-8"))
    assert len(calls) == 1
    assert "可能" in calls[0]
    assert tracking["douyin_MS4wABC"]["latest_count"] == 12
    assert tracking["douyin_MS4wABC"]["mode"] == "count"


def test_main_count_mode_no_notify_when_unchanged(tmp_path, monkeypatch):
    """count 模式：作品数不变 → 不推送。"""
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
               tracking={"douyin_MS4wABC": {"sec_uid": "MS4wABC", "mode": "count",
                                            "latest_aweme_id": "count:12", "latest_ct": 12, "latest_count": 12}})
    calls = []
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: _count_aweme(12))

    cnp.main()

    assert calls == []


def test_main_count_mode_first_run_no_notify(tmp_path, monkeypatch):
    """count 模式首次运行：仅建立基线，不推送（避免启用即轰炸）。"""
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}], tracking=None)
    calls = []
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: _count_aweme(12))

    cnp.main()

    tracking = json.loads(tf.read_text(encoding="utf-8"))
    assert calls == []
    assert tracking["douyin_MS4wABC"]["latest_count"] == 12
    assert tracking["douyin_MS4wABC"]["mode"] == "count"


def test_main_mode_switch_no_false_notify(tmp_path, monkeypatch):
    """模式切换（api 基线 → count 结果）：无法确定是否真有新作品，仅静默重建基线，不误报。"""
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
               tracking={"douyin_MS4wABC": {"sec_uid": "MS4wABC", "mode": "api",
                                            "latest_aweme_id": "888", "latest_ct": 1700000000}})
    calls = []
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    # 之前是 api 基线，现在环境无 Cookie → 退化到 count 推测
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: _count_aweme(999))

    cnp.main()

    tracking = json.loads(tf.read_text(encoding="utf-8"))
    assert calls == []  # 不应误报
    assert tracking["douyin_MS4wABC"]["mode"] == "count"
    assert tracking["douyin_MS4wABC"]["latest_aweme_id"] == "count:999"


def test_load_douyin_cookie(monkeypatch):
    monkeypatch.delenv("DOUYIN_COOKIE", raising=False)
    monkeypatch.setenv("BLIVE_CONFIG", '{"douyin_cookie": "sessionid=abc; t=1"}')
    assert cnp.load_douyin_cookie() == "sessionid=abc; t=1"
    # 环境变量优先
    monkeypatch.setenv("DOUYIN_COOKIE", "sessionid=env")
    assert cnp.load_douyin_cookie() == "sessionid=env"


def test_apply_douyin_cookie():
    ctx = FakeCtx(FakePage())
    cnp.apply_douyin_cookie(ctx, "")           # 空 -> 不注入
    assert ctx.cookies == []
    cnp.apply_douyin_cookie(ctx, "a=1; b=2")
    assert len(ctx.cookies) == 2
    assert ctx.cookies[0]["domain"] == ".douyin.com"
    assert ctx.cookies[0]["name"] == "a" and ctx.cookies[0]["value"] == "1"


def test_main_applies_cookie_via_env(tmp_path, monkeypatch):
    """main() 应通过 DOUYIN_COOKIE 注入 Cookie 到浏览器上下文。"""
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
               tracking=None, push_cfg="{}")
    calls = []
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: {
        "aweme_id": "999", "desc": "x", "video_url": "https://v/999",
        "is_note": False, "nickname": "阿伟", "create_time": 1700000000,
    })
    monkeypatch.setenv("DOUYIN_COOKIE", "sessionid=xyz")

    # 让 main 用会记录 add_cookies 的假上下文
    captured = {}

    class RecCtx(FakeCtx):
        pass

    orig_new_ctx = None
    # 替换 playwright 假上下文的 new_context 以记录 cookie
    class RecBrowser:
        def new_context(self, **kw):
            self._ctx = RecCtx(FakePage())
            captured["ctx"] = self._ctx
            return self._ctx

        def close(self):
            pass

    class RecPW:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        chromium = type("C", (), {"launch": staticmethod(lambda **kw: RecBrowser())})()

    sys.modules["playwright.sync_api"].sync_playwright = lambda: RecPW()

    cnp.main()

    assert "ctx" in captured
    assert captured["ctx"].cookies, "应已注入 DOUYIN_COOKIE"
    assert captured["ctx"].cookies[0]["value"] == "xyz"
