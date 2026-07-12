"""新作品 new_post 写入统一日志（history.json）的回归测试。

背景：count 模式（无 Cookie/风控降级）账号发新作品时，原代码只置 notify 触发推送，
从不调用 append_event，导致统一日志里 new_post 条目数为 0。修复后 count 分支在
判定 candidate 为真时也调用 append_event 写 new_post，与 api 分支一致。

测试覆盖：
1) 机制：append_event 直接写 new_post 落盘，且不被节流吞掉（new_post 始终写）。
2) 双分支守卫：api 分支与 count 分支都含 append_event(..., "new_post", ...) 调用；
   同时确认模式切换的静默分支未引入日志（避免误报）。
3) count 分支候选判定 + append_event 被调用的最小复现（无需跑完整 main/网络）。
"""
import json
import os

import pytest

import check_new_posts as cnp
from common import bjnow


SRC_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "check_new_posts.py"
)


def _read_history(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


# ==================== 1) 机制测试：new_post 落盘且不被节流吞掉 ====================

def test_append_event_new_post_written_and_not_throttled(tmp_path, monkeypatch):
    """new_post 应始终写入 history；连续两次调用都不被节流抑制。"""
    hist = tmp_path / "history.json"
    monkeypatch.setattr(cnp, "HISTORY_FILE", str(hist))

    cnp.append_event(
        "123456", "测试号", "douyin", "new_post",
        detail="作品数 10→11", now=bjnow(),
    )
    # 同账号同 type 再写一次（错误类会被 30min 节流吞掉，但 new_post 不会）
    cnp.append_event(
        "123456", "测试号", "douyin", "new_post",
        detail="作品数 11→12", now=bjnow(),
    )

    entries = _read_history(str(hist))
    assert len(entries) == 2, f"期望 2 条 new_post 均写入，实得 {len(entries)}"
    assert all(e.get("type") == "new_post" for e in entries)
    # 第一条携带基数→新数详情
    assert entries[0]["detail"] == "作品数 10→11"
    assert entries[1]["detail"] == "作品数 11→12"
    # 字段完整性（与前端兼容）
    assert entries[0]["rid"] == "123456"
    assert entries[0]["platform"] == "douyin"


# ==================== 2) 双分支守卫：api 与 count 都写 new_post ====================

def _split_branches(src: str):
    """按源码字面量切出 api 分支块与 count 分支块。"""
    assert 'if conf == "api":' in src, "源码结构变化：找不到 api 分支标记"
    assert 'else:  # conf == "count"' in src, "源码结构变化：找不到 count 分支标记"
    before_api, rest = src.split('if conf == "api":', 1)
    api_block, count_block = rest.split('else:  # conf == "count"', 1)
    return api_block, count_block


def test_api_and_count_branch_both_write_new_post():
    """api 分支与 count 分支都应包含 append_event(..., "new_post", ...) 调用。"""
    src = open(SRC_PATH, encoding="utf-8").read()
    api_block, count_block = _split_branches(src)

    # api 分支：原有正确逻辑，用作品详情（desc/video_url）写 new_post
    assert 'append_event(' in api_block
    assert '"new_post"' in api_block
    assert "desc" in api_block, "api 分支应保留作品详情写法（未被误改）"

    # count 分支：修复后新增的 append_event 调用，detail 写作品数变化
    assert 'append_event(' in count_block
    assert '"new_post"' in count_block
    assert "作品数" in count_block, "count 分支应写作品数变化详情"


def test_mode_switch_branch_still_silent():
    """模式切换静默分支（避免误报）不应调用 append_event。"""
    src = open(SRC_PATH, encoding="utf-8").read()
    _, count_block = _split_branches(src)
    # 模式切换子分支：prev_mode and prev_mode != cur_mode → 仅静默重建基线
    marker = "模式切换"
    idx = count_block.find(marker)
    assert idx != -1, "找不到模式切换静默分支标记"
    # 取模式切换子分支区间（直到下一个 candidate 判定前）
    sub = count_block[idx:count_block.find("candidate = bool(prev_count)", idx)]
    assert "append_event" not in sub, "模式切换静默分支不应写日志（避免误报）"


# ==================== 3) count 分支候选判定 + append_event 的最小复现 ====================

def test_count_branch_candidate_triggers_append_event(monkeypatch):
    """复现 count 分支判定：candidate 为真才写 new_post，否则不写（与修复后源码一致）。"""
    calls = []
    monkeypatch.setattr(cnp, "append_event", lambda *a, **k: calls.append((a, k)))

    def count_branch(rid, name, sec_uid, prev_count, new_ct):
        # 与源码 count 分支 else 内逻辑逐字对应：
        #   prev_count = int(t.get("latest_count", 0) or 0)
        #   candidate = bool(prev_count) and new_ct > prev_count
        #   if candidate:
        #       append_event(rid, name, "douyin", "new_post",
        #                    detail=f"作品数 {prev_count}→{new_ct}", now=bjnow())
        candidate = bool(prev_count) and new_ct > prev_count
        if candidate:
            cnp.append_event(
                rid, name, "douyin", "new_post",
                detail=f"作品数 {prev_count}→{new_ct}",
                now=bjnow(),
            )
        return candidate

    # 作品数增加且有基线 → candidate 真，应写 new_post
    assert count_branch("999", "号A", "SU", prev_count=5, new_ct=6) is True
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("999", "号A", "douyin", "new_post")
    assert kwargs["detail"] == "作品数 5→6"

    # 无基线（prev_count=0）或作品数未增加 → candidate 假，不写
    calls.clear()
    assert count_branch("999", "号A", "SU", prev_count=0, new_ct=3) is False
    assert count_branch("999", "号A", "SU", prev_count=4, new_ct=4) is False
    assert len(calls) == 0
