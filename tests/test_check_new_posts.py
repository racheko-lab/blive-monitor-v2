"""check_new_posts 单元测试：导入可行性、模块复用 common、新作品基线判定（纯函数）。"""
import json
import os
import sys
import types

import pytest

import check_new_posts as cnp


# ==================== 日志模块重构：注释修正 / 级联清理 / 补丁归一 ====================

def test_no_two_layer_comment_in_source():
    """D1：头部/内联『两层策略』注释应已改为『三层策略』。"""
    src_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "check_new_posts.py"
    )
    text = open(src_path, encoding="utf-8").read()
    assert "两层策略" not in text
    assert "三层策略" in text


def test_cnp_imports_state_prune_and_log_utils():
    """T02/T04：脚本已收口到横切模块。"""
    assert hasattr(cnp, "state_prune")
    assert hasattr(cnp, "init_runtime_logging")


def test_prune_tracking_orphans_equivalence():
    """A5：prune_tracking_orphans 与原 772-801 内联补丁语义一致（删不在 active 的 key）。"""
    tracking = {
        "douyin_A": {"latest_aweme_id": "1"},
        "douyin_B": {"latest_aweme_id": "2"},
        "douyin_C": {"latest_aweme_id": "3"},
    }
    cur_keys = {"douyin_A", "douyin_C"}
    out = cnp.state_prune.prune_tracking_orphans(tracking, cur_keys)
    assert set(out.keys()) == {"douyin_A", "douyin_C"}


def test_merge_post_rooms_fields_equivalence(tmp_path):
    """A6：merge_post_rooms_fields 与原 772-801 内联补丁等价（原地更新 sec_uid/name）。"""
    cfg = tmp_path / "post_rooms.json"
    cfg.write_text(json.dumps([
        {"id": "A", "name": "oldA", "sec_uid": ""},
        {"id": "B", "name": "B", "sec_uid": "SB"},
    ]), encoding="utf-8")
    # resolved 模拟本轮解析结果（仅取确有 sec_uid 的账号）
    post_rooms = [
        {"id": "A", "name": "newA", "sec_uid": "SA"},
        {"id": "B", "name": "B", "sec_uid": "SB"},
    ]
    resolved = {str(e["id"]): e for e in post_rooms if e.get("id") and e.get("sec_uid")}
    changed = cnp.state_prune.merge_post_rooms_fields(str(cfg), resolved)
    assert changed is True
    data = json.loads(cfg.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in data}
    assert by_id["A"]["sec_uid"] == "SA" and by_id["A"]["name"] == "newA"
    assert by_id["B"]["sec_uid"] == "SB"  # B 的 sec_uid 也按 resolved 更新


# ---------- 假 Playwright：让 main() 的惰性 import 可用，无需真实浏览器 ----------
class _FakeContext:
    def __init__(self, page=None):
        self._page = page
        self.cookies = []
        self.browser = _FakeBrowser(self)

    def new_page(self):
        return self._page

    def add_cookies(self, cookies):
        self.cookies.extend(cookies)

    def close(self):
        pass


class _FakeBrowser:
    def __init__(self, owner=None):
        self.owner = owner

    def new_context(self, **kwargs):
        # 单测：复用发起方的同一个 page，使移动端/桌面端抓取共用同一 FakePage
        return self.owner if self.owner is not None else _FakeContext()

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
    # 隔离 HISTORY_FILE，避免新作品/错误写入污染仓库真实 history.json
    monkeypatch.setattr(cnp, "HISTORY_FILE", str(tmp_path / "history.json"))
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


class _FakeCtxBrowser:
    """移动端 new_context 复用同一个 FakeCtx，使移动端/桌面端抓取共用同一 FakePage。"""
    def __init__(self, owner):
        self.owner = owner

    def new_context(self, **kwargs):
        return self.owner

    def close(self):
        pass


class FakeCtx:
    def __init__(self, page):
        self._page = page
        self.cookies = []
        self.browser = _FakeCtxBrowser(self)

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


def test_get_latest_aweme_mobile_v2_first():
    """移动端 v2 接口（无 Cookie）应作为首选精确路径，标记 _src=mobile。"""
    page = FakePage(responses=[
        ("https://m.douyin.com/web/api/v2/aweme/post/?x=1", json.dumps(POPULATED)),
    ])
    res = cnp.get_latest_aweme(FakeCtx(page), "MS4wSEC")
    assert res is not None
    assert res["aweme_id"] == "999"
    assert res["_conf"] == "api"
    assert res["_src"] == "mobile"


def test_get_latest_aweme_mobile_preferred_over_desktop():
    """移动端与桌面端同时返回作品时，优先采用移动端（_src=mobile）。"""
    page = FakePage(responses=[
        ("https://m.douyin.com/web/api/v2/aweme/post/?x=1", json.dumps(POPULATED)),
        ("https://www.douyin.com/aweme/v1/web/aweme/post/?x=2", json.dumps(POPULATED)),
    ])
    res = cnp.get_latest_aweme(FakeCtx(page), "MS4wSEC")
    assert res is not None
    assert res["_src"] == "mobile"


def test_get_latest_aweme_desktop_when_no_mobile():
    """仅桌面端 v1 接口有作品、移动端无 → 退化为桌面端（_src=desktop）。"""
    page = FakePage(responses=[
        ("https://www.douyin.com/aweme/v1/web/aweme/post/?x=2", json.dumps(POPULATED)),
    ])
    res = cnp.get_latest_aweme(FakeCtx(page), "MS4wSEC")
    assert res is not None
    assert res["_src"] == "desktop"


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


# ==================== sec_uid 解析（房主本人，绝不取推荐流） ====================

HOST_HTML = (
    'var render={"anchor":{"id_str":"3378120049041741",'
    '"sec_uid":"MS4wLjABAAAASecHost000","nickname":"房主本人"},'
    '"feed":[{"author":{"sec_uid":"MS4wLjABAAAASecRec999","nickname":"推荐流陌生人"}}]}'
)

# RENDER_DATA 转义形态：引号被转义为 \"，花括号不转义。
# 真实案例：live.douyin.com/81197422897 的直播页里，唯一的未转义 "anchor" 是
# <script ... "anchor" nonce=""> 的 HTML 属性（非 JSON），真正的房主 JSON 在转义形态里。
HOST_HTML_ESCAPED = (
    '<script "anchor" nonce=""></script>'
    'var render=\\"anchor\\":{\\"id_str\\":\\"2184080776246480\\",'
    '\\"sec_uid\\":\\"MS4wLjABAAAAaBxG5OhPShhY5L6dwkQqHjwJg6Tx70esLegv5Hc_ib6ZMfAJNAAWzLuHgnDZ5EsE\\",'
    '\\"nickname\\":\\"整天白日梦\\"},'
    '\\"feed\\":[{\\"author\\":{\\"sec_uid\\":\\"MS4wLjABAAAASecRec999\\"}}]}\\'
)


def test_extract_host_sec_uid_prefers_anchor_over_recommendation():
    """整页虽含推荐流陌生人的 MS4w，但只应取房间主人 anchor 的 sec_uid。"""
    got = cnp.extract_host_sec_uid(HOST_HTML)
    assert got == "MS4wLjABAAAASecHost000"
    assert got != "MS4wLjABAAAASecRec999"


def test_extract_host_sec_uid_none_when_missing():
    """页面无 anchor / roomInfo 结构（如未渲染）→ 返回 None，绝不瞎猜。"""
    assert cnp.extract_host_sec_uid('{"feed":[{"author":{"sec_uid":"MS4wLjABAAAASecRec999"}}]}') is None
    assert cnp.extract_host_sec_uid("") is None


def test_extract_host_sec_uid_handles_escaped_render_data():
    """RENDER_DATA 转义形态（引号转义、花括号不转义）也能取到房主本人 sec_uid。

    关键：未转义的 "anchor" 是 <script> 的 HTML 属性（非 JSON），绝不能误取；
    真正的房主在转义 JSON 里。同时整页充斥推荐流陌生人的转义 MS4w，也必须忽略。
    """
    got = cnp.extract_host_sec_uid(HOST_HTML_ESCAPED)
    assert got == "MS4wLjABAAAAaBxG5OhPShhY5L6dwkQqHjwJg6Tx70esLegv5Hc_ib6ZMfAJNAAWzLuHgnDZ5EsE"
    assert got != "MS4wLjABAAAASecRec999"


def test_main_poison_guard_skips_wrong_account(tmp_path, monkeypatch):
    """中毒防护：handle 型账号运行时解析到了错误 sec_uid（被推荐流污染）→ 跳过、不推送、并清除毒值。

    关键契约（与代码一致）：
    - rid 必须是 handle（`looks_like_handle` 才为真，才能用 unique_id 反查）；
      若 rid 本身是 sec_uid 形态（MS4w 开头），反查无意义，防护刻意不触发。
    - 毒值必须来自「运行时解析」（`sec_trusted=False`）：即 tracking / entry 里都没有
      预存 sec_uid，靠 resolve_sec_uid 解析出被污染的 sec_uid。若 sec_uid 是用户手填的
      可信值（stored_sec 命中），代码选择信任它、仅告警不清值，那是另一条有意分支。
    """
    _install_fake_playwright()
    # 用 handle 作 id，且不预置 stored sec_uid → 运行时解析（不可信，需反查）
    tf = _seed(tmp_path, monkeypatch, [{"id": "weiren_handle", "name": "阿伟"}],
               tracking=None)
    calls = []
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    # get_latest_aweme 实际打开的是陌生人主页（unique_id 与期望 handle 不符）
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: {
        **_count_aweme(12), "actual_unique_id": "stranger_xyz",
    })

    cnp.main()

    tracking = json.loads(tf.read_text(encoding="utf-8"))
    assert calls == []                                    # 不应误推送陌生人的「新作品」
    assert "sec_uid" not in tracking["douyin_weiren_handle"]  # 毒值被清除，下次重解


def test_main_poison_guard_skipped_for_sec_uid_id(tmp_path, monkeypatch):
    """有意行为：当 rid 本身就是 sec_uid（用户手填可信值）时，中毒防护不触发、保留该值。

    反查的前提是 rid 为 handle（能跟 profile 的 unique_id 比对）；rid 已是 sec_uid 形态时
    `looks_like_handle` 返回 False，代码信任用户手填的 sec_uid、仅告警不清值。这条分支必须
    被锁住，避免将来误改 `looks_like_handle` 而破坏"用户预存 sec_uid 账号"的正常工作。
    """
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
               tracking={"douyin_MS4wABC": {"sec_uid": "MS4wABC", "mode": "count",
                                            "latest_aweme_id": "count:10", "latest_ct": 10, "latest_count": 10}})
    calls = []
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    # 即便是「错误」账号的 unique_id，因为 rid 是 sec_uid 形态（可信），防护不触发
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: {
        **_count_aweme(12), "actual_unique_id": "stranger_xyz",
    })

    cnp.main()

    tracking = json.loads(tf.read_text(encoding="utf-8"))
    # sec_uid 形态 id 视为可信，保留，不清除
    assert "sec_uid" in tracking["douyin_MS4wABC"]
    # 该账号正常走检测（count 10→12 推测推送），不因为 unique_id 不符而误杀
    assert len(calls) == 1


# ==================== 日志模块功能性重写：新作品/错误进统一日志 ====================

def _hist_types(tmp_path):
    hist = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    return hist


def test_new_post_written_to_history(tmp_path, monkeypatch):
    """检测到真实新作品（api + candidate）时，向 history 写一条 type=new_post。"""
    _install_fake_playwright()
    _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
          tracking={"douyin_MS4wABC": {"sec_uid": "MS4wABC", "latest_aweme_id": "888", "latest_ct": 1699999000}})
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: {
        "aweme_id": "999", "desc": "新视频", "video_url": "https://v/999",
        "is_note": False, "nickname": "阿伟", "create_time": 1700000000,
    })
    cnp.main()
    hist = _hist_types(tmp_path)
    np = [e for e in hist if e.get("type") == "new_post"]
    assert len(np) == 1
    assert np[0]["rid"] == "MS4wABC"
    assert np[0]["platform"] == "douyin"
    assert np[0]["level"] == "info"
    assert "999" in (np[0]["detail"] or "")


def test_cookie_warn_written_when_gated(tmp_path, monkeypatch):
    """接口被风控/未登录（aweme=None）→ 写一条 type=cookie_warn（level=warn）。"""
    _install_fake_playwright()
    _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
          tracking={"douyin_MS4wABC": {"sec_uid": "MS4wABC", "latest_aweme_id": "888", "latest_ct": 1699999000}})
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: None)
    cnp.main()
    hist = _hist_types(tmp_path)
    cw = [e for e in hist if e.get("type") == "cookie_warn"]
    assert len(cw) >= 1
    assert cw[0]["level"] == "warn"
    assert cw[0]["rid"] == "MS4wABC"


def test_error_written_on_fetch_exception(tmp_path, monkeypatch):
    """抓取异常（get_latest_aweme 抛出）→ 写一条 type=error，detail 含异常信息。"""
    _install_fake_playwright()
    _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
          tracking={"douyin_MS4wABC": {"sec_uid": "MS4wABC", "latest_aweme_id": "888", "latest_ct": 1699999000}})
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: True)

    def boom(ctx, sec):
        raise RuntimeError("网络超时")

    monkeypatch.setattr(cnp, "get_latest_aweme", boom)
    cnp.main()
    hist = _hist_types(tmp_path)
    err = [e for e in hist if e.get("type") == "error"]
    assert len(err) >= 1
    assert "网络超时" in (err[0]["detail"] or "")
    assert err[0]["level"] == "error"


def test_cookie_warn_throttled_within_window(tmp_path, monkeypatch):
    """同账号 cookie_warn 在 30min 窗口内仅写一次（防刷屏）。"""
    _install_fake_playwright()
    _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
          tracking={"douyin_MS4wABC": {"sec_uid": "MS4wABC", "latest_aweme_id": "888", "latest_ct": 1699999000}})
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: None)
    cnp.main()
    cw1 = sum(1 for e in _hist_types(tmp_path) if e.get("type") == "cookie_warn")
    cnp.main()  # 秒级间隔，窗口内 → 抑制
    cw2 = sum(1 for e in _hist_types(tmp_path) if e.get("type") == "cookie_warn")
    assert cw2 == cw1, "30min 窗口内同账号 cookie_warn 应被节流，不重复写"


def test_system_written_when_sec_uid_missing(tmp_path, monkeypatch):
    """缺 sec_uid 且无法解析 → 降级 type=system 跳过（不写垃圾 error 刷屏）。"""
    _install_fake_playwright()
    # 无 sec_uid、且 resolve_sec_uid 返回空（模拟解析失败）
    _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
          tracking={"douyin_MS4wABC": {"latest_aweme_id": "888", "latest_ct": 1699999000}})
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: True)
    monkeypatch.setattr(cnp, "resolve_sec_uid", lambda ctx, rid: "")  # 解析失败
    cnp.main()
    hist = _hist_types(tmp_path)
    sys = [e for e in hist if e.get("type") == "system"]
    assert len(sys) >= 1
    assert sys[0]["level"] == "info"
    # 不应出现 error/cookie_warn 刷屏
    assert not any(e.get("type") in ("error", "cookie_warn") for e in hist)


def test_main_poison_guard_ok_when_handle_matches(tmp_path, monkeypatch):
    """sec_uid 实际账号与期望 handle 一致 → 正常走检测流程，不误触发防护。"""
    _install_fake_playwright()
    tf = _seed(tmp_path, monkeypatch, [{"id": "MS4wABC", "name": "阿伟"}],
               tracking={"douyin_MS4wABC": {"sec_uid": "MS4wABC", "mode": "count",
                                            "latest_aweme_id": "count:10", "latest_ct": 10, "latest_count": 10}})
    calls = []
    monkeypatch.setattr(cnp, "dispatch_push", lambda cfg, t, d: calls.append(t) or True)
    monkeypatch.setattr(cnp, "get_latest_aweme", lambda ctx, sec: {
        **_count_aweme(12), "actual_unique_id": "MS4wABC",
    })

    cnp.main()

    tracking = json.loads(tf.read_text(encoding="utf-8"))
    assert len(calls) == 1          # 作品数 10→12 正常推测推送
    assert "sec_uid" in tracking["douyin_MS4wABC"]  # 未误清
