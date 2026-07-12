#!/usr/bin/env python3
"""
定时摘要自动投递（A1）— CI 投递 CLI。

机制（详见 docs/a1_summary_design.md）：
  1. gate（守卫）：读 ``BLIVE_CONFIG.summary``；未启用 / 未到 sendTime / 本周期已投 /
     同周期失败冷却中 -> 直接 exit 0，不投递。
  2. 计算：从本轮已更新的 history.json 取 since 之后的 live_on/new_post 事件，按房间
     去重聚合（与前端 computeSummary 同口径）。
  3. 投递：调用 push_utils.dispatch_push（单通道，内部已重试），返回 SendResult。
  4. 状态回写：成功 -> 写 summary_state.json.lastSent；失败 -> 写 lastFailedAt/
     lastFailedSince（冷却用），不写 lastSent，下一轮自动重试。

退出码：一律 exit 0（非致命），配合 check.yml 的 continue-on-error，绝不阻断
状态持久化 / Pages 部署。

依赖：仅 Python 标准库 + 复用 common / push_utils。不新增任何第三方依赖。
"""
import calendar
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from common import bjnow, load_json_file, save_json_file, parse_beijing
import common  # A2/A4 统一路由：common.resolve_channel（dispatch_event 同源）
import push_utils

logger = logging.getLogger(__name__)

# 同周期失败冷却（防刷屏）。默认 4h，可由 env SUMMARY_RETRY_COOLDOWN（秒）覆盖。
DEFAULT_COOLDOWN_SECONDS = 4 * 3600

# 当前工作区文件名（persist step 会用 git add -f 强制纳入，跨 run 保留）。
STATE_FILENAME = "summary_state.json"
HISTORY_FILENAME = "history.json"


# ==================== 纯函数（与 monitor.html JS 逐字节一致，可单测） ====================

def compute_since(freq: str, now_bj: datetime) -> int:
    """北京当日午夜（daily）/ 本周一午夜（weekly）的真实 UTC 秒。

    对齐 JS ``computeSince``：``Date.UTC(y,m,d,0,0,0) - 8h``。
    now_bj 为北京 naive datetime（bjnow() 产出）。

    Args:
        freq: 'daily' 或 'weekly'。
        now_bj: 当前北京时间（naive datetime）。

    Returns:
        对应北京午夜的真实 UTC 秒（int）。
    """
    d = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    if freq == "weekly":
        # Python weekday(): 周一=0..周日=6，等价 JS getDay() 周日=0 时 diff=(day===0?6:day-1)
        d = d - timedelta(days=d.weekday())
    return calendar.timegm(d.timetuple()) - 8 * 3600


def compute_summary(hist: list, since: int) -> Dict[str, Any]:
    """聚合 hist 中 since 之后（含）的 live_on / new_post 事件。

    对齐 JS ``computeSummary``：
      - t = l.type || l.status；仅 live_on / new_post 计入。
      - ts = parse_beijing(l.time)；ts 为 None 或 < since*1000 跳过。
      - 房间 key = (platform||'') + '|' + String(rid||account||'')。
      - liveOnCount = 去重房间数；newPostCount = 新作总数。
      - rangeText = since 对应北京日期 YYYY-MM-DD。

    Args:
        hist: 历史事件列表（每行含 type/status, time, platform, rid/account, name）。
        since: compute_since 产出的北京起点 epoch 秒。

    Returns:
        ``{liveOnCount, newPostCount, byRoom, rangeText}``。
    """
    by_room: Dict[str, Dict[str, Any]] = {}
    new_post_total = 0
    for ev in hist or []:
        if not isinstance(ev, dict):
            continue
        t = ev.get("type") or ev.get("status")
        if t not in ("live_on", "new_post"):
            continue
        ts = parse_beijing(ev.get("time"))
        if ts is None or ts < since:
            continue
        rid = str(ev.get("rid") or ev.get("account") or "")
        key = (ev.get("platform") or "") + "|" + rid
        room = by_room.get(key)
        if room is None:
            room = {
                "platform": ev.get("platform") or "",
                "id": rid,
                "name": ev.get("name") or "",
                "liveOn": 0,
                "newPost": 0,
            }
            by_room[key] = room
        if t == "live_on":
            room["liveOn"] += 1
        else:
            room["newPost"] += 1
            new_post_total += 1
    by_room_list = list(by_room.values())
    sd = datetime.utcfromtimestamp(since + 8 * 3600)
    range_text = sd.strftime("%Y-%m-%d")
    return {
        "liveOnCount": len(by_room_list),
        "newPostCount": new_post_total,
        "byRoom": by_room_list,
        "rangeText": range_text,
    }


def format_summary(summary: Dict[str, Any], freq: str, range_text: str) -> Tuple[str, str]:
    """生成推送 (title, desp)；复用前端 copySummary 文案口径。

    title = ``(今日|本周)摘要（rangeText）``
    desp  = ``N 人开播 · M 条新作`` + 按房间明细
            ``- 名称：开播X 次 / 新作Y 条``

    Args:
        summary: compute_summary 的产出。
        freq: 'daily' / 'weekly'，决定「今日/本周」。
        range_text: compute_summary 产出的 rangeText。

    Returns:
        (title, desp) 元组。
    """
    label = "本周" if freq == "weekly" else "今日"
    title = f"{label}摘要（{range_text}）"
    live_on_count = summary.get("liveOnCount", 0)
    new_post_count = summary.get("newPostCount", 0)
    desp = f"{live_on_count} 人开播 · {new_post_count} 条新作"
    by_room = summary.get("byRoom") or []
    if by_room:
        lines = [
            f"- {r.get('name') or r.get('id')}：开播{r.get('liveOn', 0)} 次 / 新作{r.get('newPost', 0)} 条"
            for r in by_room
        ]
        desp += "\n" + "\n".join(lines)
    return title, desp


def should_deliver(cfg: Dict[str, Any], now_bj: datetime, state: Dict[str, Any]) -> Tuple[bool, str]:
    """四态 gate 判定：是否应当投递本周期摘要。

    reason ∈ {'disabled','too_early','already_sent','cooldown','deliver'}。

    判定顺序（依据设计 §3.2）：
      1. enabled != True                            -> (False, 'disabled')
      2. now_bj < 当日 sendTime(北京)               -> (False, 'too_early')
      3. lastSent(from state/cfg) >= since          -> (False, 'already_sent')
      4. 同周期失败冷却中(lastFailedSince==since 且 <冷却) -> (False, 'cooldown')
      5. 否则                                       -> (True, 'deliver')

    Args:
        cfg: BLIVE_CONFIG.summary 配置 dict。
        now_bj: 当前北京时间（naive datetime）。
        state: summary_state.json 载入的 dict。

    Returns:
        (should_deliver: bool, reason: str)。
    """
    if cfg.get("enabled") != True:  # noqa: E712  (显式与 True 比较，语义：未启用)
        return (False, "disabled")

    freq = cfg.get("freq", "daily")
    since = compute_since(freq, now_bj)

    # 2. 是否已到当日 sendTime（北京时）
    send_time = cfg.get("sendTime") or "00:00"
    try:
        hh, mm = str(send_time).split(":")
        send_at = now_bj.replace(
            hour=int(hh) % 24, minute=int(mm) % 60, second=0, microsecond=0
        )
    except Exception:
        # 解析失败：退化为当日午夜（即视为已到，不拦截）
        send_at = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    if now_bj < send_at:
        return (False, "too_early")

    # 3. 本周期是否已投（防重投）
    last_sent = state.get("lastSent") or cfg.get("lastSent") or 0
    if last_sent >= since:
        return (False, "already_sent")

    # 4. 同周期失败冷却（防刷屏）；跨周期(lastFailedSince!=since)不生效
    last_failed_at = state.get("lastFailedAt")
    last_failed_since = state.get("lastFailedSince")
    cooldown = int(os.environ.get("SUMMARY_RETRY_COOLDOWN", DEFAULT_COOLDOWN_SECONDS))
    if (
        last_failed_at is not None
        and last_failed_since == since
        and (int(time.time()) - int(last_failed_at)) < cooldown
    ):
        return (False, "cooldown")

    return (True, "deliver")


# ==================== 状态镜像读写（合并保留前端字段） ====================

def load_summary_state(path: str) -> Dict[str, Any]:
    """读取 summary_state.json；文件不存在/解析失败返回 {}。"""
    return load_json_file(path, default={})


def save_summary_state(path: str, data: Dict[str, Any], remove: Optional[list] = None) -> None:
    """读旧 -> 合并更新 -> 原子写 summary_state.json。

    保留前端既有 enabled/freq/sendTime 字段，仅更新调用方传入的字段
    （lastSent / lastFailedAt / lastFailedSince 等）。绝不直接覆盖整文件。
    remove: 可选键列表，合并后从结果中显式删除（用于清除失败冷却字段）。
    """
    old = load_summary_state(path)
    merged = dict(old)
    merged.update(data)
    for k in (remove or []):
        merged.pop(k, None)
    save_json_file(path, merged)


# ==================== 编排入口 ====================

def main() -> None:
    """读 env -> gate -> 计算 -> 投递 -> 回写；全程 exit 0（非致命）。

    Raises:
        SystemExit: 任何分支均以 sys.exit(0) 退出，绝不阻断 CI 主流程。
    """
    try:
        raw = os.environ.get("BLIVE_CONFIG", "")
        cfg_all = json.loads(raw) if raw else {}
        summary_cfg = cfg_all.get("summary") or {}

        state = load_summary_state(STATE_FILENAME)
        now_bj = bjnow()
        freq = summary_cfg.get("freq", "daily")
        since = compute_since(freq, now_bj)

        ok, reason = should_deliver(summary_cfg, now_bj, state)
        logging.info(
            "摘要 gate 结果: reason=%s freq=%s since=%s", reason, freq, since
        )
        if not ok:
            sys.exit(0)

        # 多通道路由：按 {event:'summary'} 选通道；无有效通道则 no-op（不写冷却，避免误配置刷屏）
        ch = common.resolve_channel(cfg_all, {"event": "summary"})
        pcfg = push_utils.channel_to_push_cfg(ch)
        if not pcfg or not pcfg.get("type"):
            logging.warning("推送未配置（无有效通道），跳过摘要投递")
            sys.exit(0)

        hist = load_json_file(HISTORY_FILENAME, default=[])
        summary = compute_summary(hist, since)
        title, desp = format_summary(summary, freq, summary["rangeText"])

        res = push_utils.dispatch_event(cfg_all, {"event": "summary"}, title, desp)
        if res.ok:
            # 成功：回写 lastSent，并清除失败冷却字段
            new_state = {
                **state,
                "enabled": summary_cfg.get("enabled"),
                "freq": summary_cfg.get("freq"),
                "sendTime": summary_cfg.get("sendTime"),
                "lastSent": int(time.time()),
            }
            save_summary_state(STATE_FILENAME, new_state, remove=["lastFailedAt", "lastFailedSince"])
            logging.info("摘要已投递（title=%s）", title)
        else:
            # 失败：写冷却字段，不写 lastSent，下一轮自动重试
            save_summary_state(
                STATE_FILENAME,
                {
                    **state,
                    "lastFailedAt": int(time.time()),
                    "lastFailedSince": since,
                },
            )
            logging.warning("摘要投递失败: %s", res.last_error or "(无错误信息)")
        sys.exit(0)
    except Exception as e:  # 兜底：绝不抛出，配合 continue-on-error
        logging.error("摘要投递异常（已忽略，不影响主流程）: %s", e)
        sys.exit(0)


def run_summary(*, cfg_all: Dict[str, Any], persist: Any, now: Optional[datetime] = None) -> None:
    """后端驱动的摘要投递编排（不写 JSON，经 ``persist`` 落库）。

    复用本模块纯函数（compute_since / compute_summary / format_summary / should_deliver）
    与 common / push_utils 的路由/推送逻辑（一字不改）；``summary_state.json`` 读写改为
    ``persist`` 回调：

        persist.get_summary_state() -> dict
        persist.set_summary_state(data) -> dict（合并写回）
        persist.get_events()         -> [{time,type,rid,account,name,platform,...}]（供 compute_summary）

    Args:
        cfg_all: BLIVE_CONFIG 完整 dict。
        persist: 后端持久化门面（见 backend/jobs/summary_job.SummaryPersist）。
        now: 当前北京时间（测试用）；缺省 ``bjnow()``。
    """
    if now is None:
        now = bjnow()
    summary_cfg = (cfg_all or {}).get("summary") or {}
    state = persist.get_summary_state()
    freq = summary_cfg.get("freq", "daily")
    since = compute_since(freq, now)

    ok, reason = should_deliver(summary_cfg, now, state)
    logging.info("摘要 gate 结果: reason=%s freq=%s since=%s", reason, freq, since)
    if not ok:
        return

    ch = common.resolve_channel(cfg_all or {}, {"event": "summary"})
    pcfg = push_utils.channel_to_push_cfg(ch)
    if not pcfg or not pcfg.get("type"):
        logging.warning("推送未配置（无有效通道），跳过摘要投递")
        return

    hist = persist.get_events() or []
    summary = compute_summary(hist, since)
    title, desp = format_summary(summary, freq, summary["rangeText"])

    res = push_utils.dispatch_event(cfg_all or {}, {"event": "summary"}, title, desp)
    if res.ok:
        new_state = {
            **state,
            "enabled": summary_cfg.get("enabled"),
            "freq": summary_cfg.get("freq"),
            "sendTime": summary_cfg.get("sendTime"),
            "lastSent": int(time.time()),
        }
        persist.set_summary_state(new_state, remove=["lastFailedAt", "lastFailedSince"])
        logging.info("摘要已投递（title=%s）", title)
    else:
        persist.set_summary_state({
            **state,
            "lastFailedAt": int(time.time()),
            "lastFailedSince": since,
        })
        logging.warning("摘要投递失败: %s", res.last_error or "(无错误信息)")


if __name__ == "__main__":
    main()
