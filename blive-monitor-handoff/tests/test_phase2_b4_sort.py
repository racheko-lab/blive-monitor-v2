"""阶段二 2b · B4 排序：前端排序控件 + Python 参考实现。

grep 契约：
  - monitor.html 必须含 sortSel（排序控件 id）/ applySort / onSortChange（函数名）。
  - 排序与 fl（平台）/ q（搜索）/ tag（标签）AND 叠加（applySort 在
    renderLive/renderPosts 排序层生效，不改数据源、不触发网络）。

Python 参考实现镜像 JS applySort（default / live / platform / recent），
并用「与 tag AND 叠加」用例验证（与 test_phase2_b2_tags 一致范式）。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")


# ---------------------------------------------------------------------------
# grep 契约
# ---------------------------------------------------------------------------
def test_html_sort_contract():
    src = open(HTML, encoding="utf-8").read()
    for token in ["sortSel", "applySort", "onSortChange"]:
        assert token in src, f"monitor.html 缺少 B4 契约标记: {token}"


def test_html_sort_applied_in_lists():
    src = open(HTML, encoding="utf-8").read()
    # renderLive 调用 applySort(rs, sortKey, {...})（sortKey 以 typeof 兜底）
    assert "applySort(rs, typeof sortKey" in src, "renderLive 未叠加 applySort"
    # renderPosts 调用 applySort(list, sortKey, {...})
    assert "applySort(list, typeof sortKey" in src, "renderPosts 未叠加 applySort"
    # 排序仅生效于排序层：applySort 输入已是过滤后的 rs/list（与 fl/q/tag AND 叠加）
    assert "rs = applyTagsFilter(rs, tag)" in src
    assert "list = applyTagsFilter(list, tag)" in src


# ---------------------------------------------------------------------------
# Python 参考实现（镜像 JS applySort）
# ---------------------------------------------------------------------------
def apply_sort(rs, sort_key, ctx=None):
    """镜像 JS applySort：default/live=状态排名；platform=B站→抖音；recent=最近活跃。"""
    ctx = ctx or {}
    status_rank = ctx.get("statusRank") or {}
    last_active = ctx.get("lastActive") or {}
    arr = list(rs)

    def srank(a):
        ka = a.get("platform", "") + "|" + str(a.get("id", ""))
        return status_rank.get(ka, 1)

    if sort_key == "platform":
        pf = {"bilibili": 0, "douyin": 1}

        def keyf(a):
            pa = pf.get(a.get("platform"), 9)
            return (pa, srank(a))

        return sorted(arr, key=keyf)
    if sort_key == "recent":

        def keyf(a):
            ka = a.get("platform", "") + "|" + str(a.get("id", ""))
            return -last_active.get(ka, 0)  # 最近活跃在前

        return sorted(arr, key=keyf)
    # default / live
    return sorted(arr, key=srank)


def _mk(platform, rid, status=None):
    r = {"platform": platform, "id": rid, "name": platform + rid}
    if status is not None:
        r["_status"] = status
    return r


def test_sort_default_status_rank():
    # 状态排名：live(0) 优先于 offline(2)
    rooms = [
        _mk("bilibili", "1", "offline"),
        _mk("douyin", "2", "live"),
        _mk("bilibili", "3", "offline"),
    ]
    status_rank = {
        "bilibili|1": 2, "douyin|2": 0, "bilibili|3": 2
    }
    out = apply_sort(rooms, "default", {"statusRank": status_rank})
    assert [r["id"] for r in out] == ["2", "1", "3"], out


def test_sort_live_priority():
    # live 与 default 同按状态排名（直播中优先）
    rooms = [
        _mk("bilibili", "1", "offline"),
        _mk("douyin", "2", "live"),
    ]
    status_rank = {"bilibili|1": 2, "douyin|2": 0}
    out = apply_sort(rooms, "live", {"statusRank": status_rank})
    assert out[0]["id"] == "2"


def test_sort_platform():
    rooms = [
        _mk("douyin", "2"),
        _mk("bilibili", "1"),
        _mk("douyin", "3"),
    ]
    status_rank = {"bilibili|1": 0, "douyin|2": 0, "douyin|3": 0}
    out = apply_sort(rooms, "platform", {"statusRank": status_rank})
    # B站（bilibili）先于抖音（douyin）
    assert [r["platform"] for r in out] == ["bilibili", "douyin", "douyin"], out


def test_sort_recent():
    rooms = [
        _mk("bilibili", "1"),
        _mk("douyin", "2"),
        _mk("bilibili", "3"),
    ]
    last_active = {
        "bilibili|1": 100, "douyin|2": 500, "bilibili|3": 300
    }
    out = apply_sort(rooms, "recent", {"lastActive": last_active})
    # 最近活跃（时间戳大）在前
    assert [r["id"] for r in out] == ["2", "3", "1"], out


def test_sort_recent_no_record_last():
    # 无记录排末尾
    rooms = [_mk("bilibili", "1"), _mk("douyin", "2")]
    last_active = {"douyin|2": 500}
    out = apply_sort(rooms, "recent", {"lastActive": last_active})
    assert out[0]["id"] == "2"


def test_sort_and_tag_and():
    """排序与 fl/q/tag AND 叠加（复刻 B2 范式）。"""
    rooms = [
        {"platform": "bilibili", "id": "1", "name": "阿尔法", "tags": ["game"], "_status": "live"},
        {"platform": "douyin", "id": "2", "name": "贝塔", "tags": ["game"], "_status": "offline"},
        {"platform": "bilibili", "id": "3", "name": "伽马", "tags": ["study"], "_status": "live"},
    ]
    # 平台过滤 fl=bilibili
    fl = [r for r in rooms if r["platform"] == "bilibili"]
    # 标签过滤 tag=game
    tag = [r for r in fl if "game" in (r.get("tags") or [])]
    status_rank = {
        "bilibili|1": 0, "douyin|2": 2, "bilibili|3": 0
    }
    out = apply_sort(tag, "live", {"statusRank": status_rank})
    assert [r["id"] for r in out] == ["1"]
