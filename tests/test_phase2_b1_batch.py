"""阶段二 2a · B1 批量增删：纯函数参考实现 + grep 契约。

提供与 monitor.html JS（parseBatchInput / mergeRooms）逻辑一致的 Python 参考实现，
并 grep 确认 batchAddBox / exportRooms / importRooms 等契约标记存在。
"""
import os
import re
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")


# ---------------------------------------------------------------------------
# grep 契约
# ---------------------------------------------------------------------------
def test_monitor_html_has_b1_batch_contract():
    src = open(HTML, encoding="utf-8").read()
    for token in ["batchAddBox", "exportRooms", "importRooms",
                  "function parseBatchInput", "function mergeRooms"]:
        assert token in src, f"monitor.html 缺少 B1 契约标记: {token}"


# ---------------------------------------------------------------------------
# Python 参考实现（镜像 JS 逻辑）
# ---------------------------------------------------------------------------
def norm_platform(p):
    p = (p or "").lower()
    if p in ("bilibili", "b站", "bili"):
        return "bilibili"
    if p in ("douyin", "抖音", "dy", "tiktok"):
        return "douyin"
    if p in ("xhs", "小红书"):
        return "xhs"
    return ""


def normalize_batch_item(it):
    if not isinstance(it, dict):
        return None
    rid = str(it["id"]) if it.get("id") is not None else ""
    if not rid:
        return None
    platform = norm_platform(it.get("platform")) if it.get("platform") else ""
    if not platform:
        platform = "douyin"  # 新作仅抖音；缺省按 douyin
    name = str(it["name"]) if it.get("name") not in (None, "") else rid
    return {"platform": platform, "id": rid, "name": name}


def parse_batch_input(text):
    ok, bad = [], []
    if not text:
        return {"ok": ok, "bad": bad}
    raw = text.strip()

    def build_from_items(items):
        for it in items:
            r = normalize_batch_item(it)
            if r:
                ok.append(r)
            else:
                bad.append({"raw": json.dumps(it, ensure_ascii=False)[:120], "reason": "缺少 platform/id"})

    if raw[0] in ("[", "{"):
        try:
            data = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            return {"ok": ok, "bad": [{"raw": raw[:200], "reason": "JSON 解析失败: " + str(e)}]}
        items = data if isinstance(data, list) else []
        if isinstance(data, dict):
            items = list(data.get("rooms", [])) + list(data.get("postRooms", []))
        build_from_items(items)
        return {"ok": ok, "bad": bad}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line[0] in ("[", "{"):
            try:
                it = json.loads(line)
            except Exception:  # noqa: BLE001
                bad.append({"raw": line, "reason": "JSON 解析失败"})
                continue
            r = normalize_batch_item(it)
            if r:
                ok.append(r)
            else:
                bad.append({"raw": line[:120], "reason": "缺少 platform/id"})
            continue
        parts = line.split("|")
        if len(parts) < 2:
            bad.append({"raw": line, "reason": "格式应为 平台|ID|名称"})
            continue
        platform = norm_platform(parts[0].strip())
        rid = parts[1].strip()
        name = parts[2].strip() if len(parts) > 2 else rid
        if not platform:
            bad.append({"raw": line, "reason": "未知平台：" + parts[0]})
            continue
        if not rid:
            bad.append({"raw": line, "reason": "ID 为空"})
            continue
        ok.append({"platform": platform, "id": rid, "name": name})
    return {"ok": ok, "bad": bad}


def merge_rooms(existing, incoming):
    existing = existing or []
    incoming = incoming or []
    out, map_ = [], {}

    def key_of(r):
        rid = str(r["id"]) if r.get("id") is not None else ""
        p = (r.get("platform") + "|") if r.get("platform") else ""
        return p + rid

    for r in existing:
        map_[key_of(r)] = r
        out.append(r)
    added = skipped = 0
    for inc in incoming:
        if not inc or inc.get("id") in (None, ""):
            continue
        item = {
            "platform": inc.get("platform"),
            "id": str(inc["id"]),
            "name": (inc.get("name") if inc.get("name") not in (None, "") else str(inc["id"])),
        }
        if not item["platform"]:
            del item["platform"]
        k = key_of(item)
        if k in map_:
            skipped += 1  # 保留 existing（含未知字段与顺序）
        else:
            map_[k] = item
            out.append(item)
            added += 1
    return {"rooms": out, "added": added, "skipped": skipped}


# ---------------------------------------------------------------------------
# 参考实现断言
# ---------------------------------------------------------------------------
def test_parse_batch_input_pipe_lines():
    text = "douyin|123|张三\nbilibili|456|李四\nbad line\nxhs|789"
    res = parse_batch_input(text)
    assert len(res["ok"]) == 3, res
    assert res["ok"][0] == {"platform": "douyin", "id": "123", "name": "张三"}
    assert res["ok"][1] == {"platform": "bilibili", "id": "456", "name": "李四"}
    assert res["ok"][2]["platform"] == "xhs"
    assert len(res["bad"]) == 1  # "bad line" 缺分隔符


def test_parse_batch_input_chinese_platform():
    text = "抖音|111|甲\nB站|222|乙"
    res = parse_batch_input(text)
    assert res["ok"][0]["platform"] == "douyin"
    assert res["ok"][1]["platform"] == "bilibili"


def test_parse_batch_input_json_array():
    text = json.dumps([{"platform": "douyin", "id": "1", "name": "A"},
                       {"id": "2", "name": "B"}])  # 缺 platform → 按 douyin
    res = parse_batch_input(text)
    assert len(res["ok"]) == 2
    assert res["ok"][1]["platform"] == "douyin"


def test_parse_batch_input_backup_object():
    text = json.dumps({"rooms": [{"platform": "bilibili", "id": "1", "name": "A"}],
                       "postRooms": [{"id": "2", "name": "B"}]})
    res = parse_batch_input(text)
    assert len(res["ok"]) == 2
    assert res["ok"][1]["platform"] == "douyin"  # 新作缺 platform → douyin


def test_merge_rooms_dedup_preserves_unknown():
    existing = [{"platform": "bilibili", "id": "1", "name": "A", "tags": ["x"], "enabled": False}]
    incoming = [{"platform": "bilibili", "id": "1", "name": "A2"},  # 重复 → 跳过，保留 existing
                {"platform": "douyin", "id": "2", "name": "B"}]     # 新增
    res = merge_rooms(existing, incoming)
    assert res["added"] == 1
    assert res["skipped"] == 1
    # existing 的未知字段 tags/enabled 被保留
    assert res["rooms"][0]["tags"] == ["x"]
    assert res["rooms"][0]["enabled"] is False
    assert len(res["rooms"]) == 2


def test_merge_rooms_post_no_platform_keys_by_id():
    existing = [{"id": "1", "name": "A", "sec_uid": "S1"}]
    incoming = [{"id": "2", "name": "B"}, {"id": "1", "name": "A2"}]  # id=1 重复
    res = merge_rooms(existing, incoming)
    assert res["added"] == 1
    assert res["skipped"] == 1
    assert res["rooms"][0]["sec_uid"] == "S1"  # 保留未知字段
    assert len(res["rooms"]) == 2
