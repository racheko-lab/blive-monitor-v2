"""阶段二 2c D2 · 写回冲突增强：enhancedMerge 字段级优先级 + 409 自愈 + 5xx/网络退避参考实现 + grep 契约。

关键红线：ghWriteWithRetry 签名 (path, mutate) 与返回形状 {rooms, changed, sha} 不变；
仅内部增强（5xx/网络退避重试、重试先 ghGetFile 重跑 mutate、enhancedMerge 字段级兜底）。
既有的 apiAddRoom/submitBatchBox/setRoomEnabled 调用方零改动。
"""
import os
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")


def _src():
    return open(HTML, encoding="utf-8").read()


# ---------------------------------------------------------------------------
# grep 契约
# ---------------------------------------------------------------------------
def test_d2_grep_contracts():
    src = _src()
    for token in ["function enhancedMerge", "function ghWriteWithRetry"]:
        assert token in src, "monitor.html 缺少 D2 契约标记: %s" % token


# ---------------------------------------------------------------------------
# Python 参考实现（镜像 JS enhancedMerge）
# ---------------------------------------------------------------------------
def enhanced_merge(local, remote):
    local = local or []
    remote = remote or []
    def key_of(r):
        rid = str(r["id"] if r.get("id") is not None else "")
        return (r["platform"] + "|" if r.get("platform") else "") + rid
    id_only = all("platform" not in r for r in local) and all("platform" not in r for r in remote)
    def k(r):
        return str(r["id"]) if (id_only and r.get("id") is not None) else key_of(r)
    map_l, map_r, out, seen = {}, {}, [], set()
    for r in local: map_l[k(r)] = r
    for r in remote: map_r[k(r)] = r

    def pick(l, r):
        if l and not r: return l
        if not l and r: return r
        m, fields = {}, set(l.keys()) | set(r.keys())
        for f in fields:
            lv, rv = l.get(f), r.get(f)
            lvn = lv is not None and str(lv).strip() != ""
            rvn = rv is not None and str(rv).strip() != ""
            if f in ("tags", "enabled"):
                m[f] = lv if lv is not None else rv            # 本地优先
            elif f in ("sec_uid", "name"):
                m[f] = rv if rvn else lv                        # 远端非空优先
            else:
                m[f] = rv if rvn else (lv if lvn else rv)       # 其余 remote 优先
        return m

    for r in local:
        key = k(r)
        if key not in seen:
            seen.add(key)
            out.append(pick(r, map_r.get(key)))
    for r in remote:
        key = k(r)
        if key not in seen:
            seen.add(key)
            out.append(pick(map_l.get(key), r))
    changed = (len(out) != len(remote)) or (
        json.dumps(out, ensure_ascii=False) != json.dumps(remote, ensure_ascii=False))
    return {"rooms": out, "changed": changed}


def test_enhanced_merge_local_tags_enabled_priority():
    local = [{"platform": "bilibili", "id": "1", "name": "A", "tags": ["x"], "enabled": False, "sec_uid": ""}]
    remote = [{"platform": "bilibili", "id": "1", "name": "B", "tags": [], "enabled": True, "sec_uid": "S1"}]
    merged = enhanced_merge(local, remote)["rooms"][0]
    assert merged["tags"] == ["x"], merged           # 本地 tags 优先
    assert merged["enabled"] is False, merged        # 本地 enabled 优先
    assert merged["sec_uid"] == "S1", merged         # 远端 sec_uid 优先
    assert merged["name"] == "B", merged             # 远端 name（非空）优先
    assert merged["platform"] == "bilibili" and merged["id"] == "1"


def test_enhanced_merge_remote_name_empty_fallback_local():
    local = [{"platform": "b", "id": "1", "name": "A", "sec_uid": ""}]
    remote = [{"platform": "b", "id": "1", "name": "", "sec_uid": "S2"}]
    merged = enhanced_merge(local, remote)["rooms"][0]
    assert merged["name"] == "A", merged             # 远端 name 空 -> 取本地
    assert merged["sec_uid"] == "S2", merged         # 远端 sec_uid 优先


def test_enhanced_merge_union_keeps_both_sides():
    local = [{"platform": "b", "id": "1", "name": "A"}]
    remote = [{"platform": "b", "id": "2", "name": "B"}]   # 仅 remote 有
    out = enhanced_merge(local, remote)["rooms"]
    keys = {r["id"] for r in out}
    assert keys == {"1", "2"}, keys                     # 并集，双方都保留


def test_enhanced_merge_preserves_unknown_remote_fields():
    # CI 写回的未知字段（sec_uid 等）在 remote 独有时应保留
    local = [{"platform": "b", "id": "1", "name": "A", "tags": ["t"]}]
    remote = [{"platform": "b", "id": "1", "name": "A", "tags": [], "sec_uid": "CI_S"}]
    merged = enhanced_merge(local, remote)["rooms"][0]
    assert merged["sec_uid"] == "CI_S", merged
    assert merged["tags"] == ["t"], merged             # 本地 tags 优先


# ---------------------------------------------------------------------------
# 409 自愈 + 重试参考实现（镜像 JS ghWriteWithRetry 内部增强）
# ---------------------------------------------------------------------------
class ConflictError(Exception):
    pass


def gh_write_with_retry_ref(get_remote, mutate, put, max_attempts=5):
    attempt = [0]

    def run(use_merge):
        file = get_remote()
        res = mutate(file["rooms"])
        if not res["changed"]:
            return {"rooms": res["rooms"], "changed": False, "sha": file["sha"]}
        payload = res["rooms"]
        if use_merge:
            payload = enhanced_merge(res["rooms"], file["rooms"])["rooms"]
        try:
            sha = put(payload, file["sha"])
        except ConflictError:
            if attempt[0] < max_attempts:
                attempt[0] += 1
                return run(True)
            raise
        return {"rooms": payload, "changed": True, "sha": sha}

    return run(False)


def test_gh_write_retry_self_heals_preserving_concurrent():
    # 第一次 PUT 遇 409；重试前远端已被并发加入 C，重跑 mutate 应保留 C 并成功
    base = [{"platform": "b", "id": "A"}]
    concurrent = [{"platform": "b", "id": "A"}, {"platform": "b", "id": "C"}]
    state = {"remote": base, "puts": 0}

    def get_remote():
        return {"rooms": [dict(r) for r in state["remote"]], "sha": "sha-%d" % state["puts"]}

    def mutate(cur):
        if any(r["id"] == "B" for r in cur):
            return {"rooms": cur, "changed": False}
        return {"rooms": cur + [{"platform": "b", "id": "B"}], "changed": True}

    def put(payload, sha):
        state["puts"] += 1
        if state["puts"] == 1:
            # 第一次：模拟 409（且此刻远端已被并发改为 concurrent）
            state["remote"] = [dict(r) for r in concurrent]
            raise ConflictError()
        return "new-sha"

    result = gh_write_with_retry_ref(get_remote, mutate, put)
    ids = {r["id"] for r in result["rooms"]}
    assert ids == {"A", "B", "C"}, ids          # 本地意图 B 与并发 C 都不丢
    assert result["changed"] is True
    assert result["sha"] == "new-sha"


def test_gh_write_exhausts_retries_then_raises():
    calls = [0]

    def get_remote():
        return {"rooms": [], "sha": "s"}

    def mutate(cur):
        return {"rooms": [{"platform": "b", "id": "X"}], "changed": True}

    def put(payload, sha):
        calls[0] += 1
        raise ConflictError()

    try:
        gh_write_with_retry_ref(get_remote, mutate, put, max_attempts=5)
        assert False, "应耗尽重试后抛出 ConflictError"
    except ConflictError:
        pass
    # 首次 PUT + 5 次重试 = 6 次 PUT 尝试
    assert calls[0] == 6, calls[0]


# ---------------------------------------------------------------------------
# 5xx / 网络退避参考实现（退避 0.5→1→2→4s 封顶 8s，≤5 次）
# ---------------------------------------------------------------------------
def backoff_schedule(n):
    seq = [500, 1000, 2000, 4000, 8000]
    return [seq[min(i, len(seq) - 1)] for i in range(n)]


def test_backoff_schedule_cap_and_length():
    # 实际重试最多 5 次，每次退避取自 5 元素序列，末位封顶 8s
    assert backoff_schedule(5) == [500, 1000, 2000, 4000, 8000]
    assert backoff_schedule(5)[-1] == 8000                       # 封顶 8s
    assert backoff_schedule(3) == [500, 1000, 2000]
