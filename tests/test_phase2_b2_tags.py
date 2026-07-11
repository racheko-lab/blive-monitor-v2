"""阶段二 2b · B2 分组标签：前端标签筛选 + Python 参考实现。

grep 契约：
  - monitor.html 必须含 roomTags（直播添加表单）/ postRoomTags（抖音号添加表单）/
    data-tag（标签 chip 维度）/ applyTagsFilter / onTagFilter / renderTagChips（函数名）。
  - 标签 chip 与 .chip 平台 / q 搜索 AND 叠加（复刻 matchQ 范式）。

Python 参考实现镜像 JS applyTagsFilter，并用「与 fl/q AND 叠加」用例验证
（防御性：缺 tags 字段不报错，视为无标签）。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")


# ---------------------------------------------------------------------------
# grep 契约
# ---------------------------------------------------------------------------
def test_html_room_tags_contract():
    src = open(HTML, encoding="utf-8").read()
    for token in [
        "roomTags",
        "postRoomTags",
        "data-tag",
        "applyTagsFilter",
        "onTagFilter",
        "renderTagChips",
    ]:
        assert token in src, f"monitor.html 缺少 B2 契约标记: {token}"


def test_html_tag_chip_uses_matchq_style():
    """标签 chip 与 .chip 平台筛选、q 搜索 AND 叠加（复刻 matchQ 范式）。"""
    src = open(HTML, encoding="utf-8").read()
    # applyTagsFilter 在 renderLive / renderPosts 中被调用（tag 过滤层）
    assert "applyTagsFilter(rs, tag)" in src, "renderLive 未叠加标签筛选"
    assert "applyTagsFilter(list, tag)" in src, "renderPosts 未叠加标签筛选"
    # 与 fl / q AND 叠加：tag 过滤发生在 fl 平台过滤与 q 文本搜索之后，且以 tag 为真为前置
    assert "rs = applyTagsFilter(rs, tag)" in src


# ---------------------------------------------------------------------------
# Python 参考实现（镜像 JS applyTagsFilter）
# ---------------------------------------------------------------------------
def apply_tags_filter(rooms, tag):
    """镜像 JS applyTagsFilter：仅返回含 tag 的房间；缺 tags 视为无标签。"""
    if not tag:
        return rooms
    out = []
    for r in rooms:
        tags = r.get("tags") or []
        if not tags:
            continue
        if tag in tags:
            out.append(r)
    return out


def test_apply_tags_filter_match():
    rooms = [
        {"platform": "bilibili", "id": "1", "name": "A", "tags": ["game"]},
        {"platform": "douyin", "id": "2", "name": "B", "tags": ["study", "game"]},
        {"platform": "douyin", "id": "3", "name": "C"},  # 无 tags
        {"platform": "bilibili", "id": "4", "name": "D", "tags": []},
    ]
    assert len(apply_tags_filter(rooms, "game")) == 2
    assert len(apply_tags_filter(rooms, "study")) == 1
    # 无标签房间在「全部」（tag=''）下仍可见
    assert len(apply_tags_filter(rooms, "")) == 4
    # 未知 tags 字段不报错（防御性读取）
    assert apply_tags_filter([{"id": "x"}], "game") == []


def test_tags_and_fl_and_q_and():
    """复刻 matchQ 范式：tag 与平台(fl) / 搜索(q) AND 叠加。"""
    rooms = [
        {"platform": "bilibili", "id": "1", "name": "阿尔法", "tags": ["game"]},
        {"platform": "douyin", "id": "2", "name": "贝塔", "tags": ["game"]},
        {"platform": "bilibili", "id": "3", "name": "伽马", "tags": ["study"]},
    ]

    def match_q(r, q):
        s = q.lower()
        return (r["name"] or "").lower().find(s) >= 0 or str(r["id"]).lower().find(s) >= 0

    # fl = 'bilibili' 平台过滤
    fl = [r for r in rooms if r["platform"] == "bilibili"]
    # + q 搜索
    q = [r for r in fl if match_q(r, "阿尔")]
    # + tag 过滤
    final = apply_tags_filter(q, "game")
    assert [r["name"] for r in final] == ["阿尔法"]
    # 仅 tag=study 在 bilibili + 搜索「伽」下命中 伽马
    assert [r["name"] for r in apply_tags_filter(
        [r for r in fl if match_q(r, "伽")], "study"
    )] == ["伽马"]
