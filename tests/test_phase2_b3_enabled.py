"""阶段二 2b · B3 批量启停：前端 checkbox + 批量条 + CI 跳过。

grep 契约：
  - monitor.html 必须含 blm-room-select（列表选择 checkbox class）/
    batchBar（批量操作条 id）/ editRoom / setRoomEnabled / pauseSelected（函数名）。
  - check_status.py 与 check_new_posts.py 必须含 room_enabled(...) 调用
    （CI 完全跳过 enabled===false 的房间检测）。
  - 暂停态保留 .blm-room-link（可点击契约不破）+ 灰显「已暂停」徽标。

Python 参考实现镜像 common.room_enabled（缺失 enabled 视为 True）。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")
CHECK_STATUS = os.path.join(ROOT, "check_status.py")
CHECK_POSTS = os.path.join(ROOT, "check_new_posts.py")

import common


# ---------------------------------------------------------------------------
# grep 契约
# ---------------------------------------------------------------------------
def test_html_batch_contract():
    src = open(HTML, encoding="utf-8").read()
    for token in [
        "blm-room-select",
        "batchBar",
        "editRoom",
        "setRoomEnabled",
        "pauseSelected",
    ]:
        assert token in src, f"monitor.html 缺少 B3 契约标记: {token}"


def test_html_preserves_room_link_and_paused_badge():
    src = open(HTML, encoding="utf-8").read()
    # 暂停态：.blm-room-card 追加 .paused + 「已暂停」徽标
    assert "(_paused?' paused':'')" in src, "未对暂停房间加 .paused 类"
    assert "已暂停" in src, "未渲染「已暂停」徽标"
    # 保留 .blm-room-link（B3 不破坏可点击契约）
    assert "blm-room-link" in src


def test_ci_room_enabled_skip():
    cs = open(CHECK_STATUS, encoding="utf-8").read()
    assert "room_enabled(room)" in cs, "check_status.py 未用 room_enabled 跳过已暂停房间"
    cp = open(CHECK_POSTS, encoding="utf-8").read()
    assert "room_enabled(entry)" in cp, "check_new_posts.py 未用 room_enabled 跳过已暂停账号"


# ---------------------------------------------------------------------------
# Python 参考实现（镜像 common.room_enabled）
# ---------------------------------------------------------------------------
def test_room_enabled_defaults():
    # 缺失 enabled → True
    assert common.room_enabled({}) is True
    assert common.room_enabled({"name": "x"}) is True
    # 显式 true → True
    assert common.room_enabled({"enabled": True}) is True
    # 显式 false → False
    assert common.room_enabled({"enabled": False}) is False
    # 非 dict → True（防御性）
    assert common.room_enabled(None) is True
    assert common.room_enabled("not a dict") is True


def test_room_enabled_skip_semantics():
    """enabled===false 才跳过；其余视为启用（与 CI 行为一致）。"""
    enabled_room = {"platform": "bilibili", "id": "1", "enabled": True}
    paused_room = {"platform": "bilibili", "id": "2", "enabled": False}
    no_flag_room = {"platform": "douyin", "id": "3"}
    assert common.room_enabled(enabled_room) is True
    assert common.room_enabled(paused_room) is False
    assert common.room_enabled(no_flag_room) is True
