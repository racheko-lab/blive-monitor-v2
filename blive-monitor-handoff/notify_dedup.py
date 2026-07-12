#!/usr/bin/env python3
"""
通知去重账本（直播监控 / 新作品监控共用）

为什么需要（重复推送的根因与防线）
--------------------------------
两个监控脚本原本只靠 Git 持久化的状态文件（state.json / tracking.json /
post_tracking.json）做去重：开播后写 "live"，下一轮读到 prev=live 就不再推送。
但这一机制有两个脆弱点，都会导致「同一条通知被重复发送」：

  1) 状态持久化偶发失败：CI 的 Persist 步骤若因网络/分叉未能把状态文件 push 回
     仓库，下一轮 checkout 到的是旧基线，会把同一次开播当成「首次检测」重新推送；
  2) 抖音直播页在 CI 无登录态下偶尔抓取失败，会退化返回 "offline"
     （check_status.fetch_douyin 的兜底分支），造成 live→offline→live 的「闪烁」，
     触发重复的「开播」通知。

本模块提供与状态持久化解耦的独立去重账本（notify_dedup.json），作为第二道防线：

  - 直播 / 回放开播：key = "live:{platform}_{rid}"，冷却 LIVE_COOLDOWN_SECONDS（默认 2h）。
    连续直播期间 prev_status=live 本就不会重复推送；冷却主要吸收「闪烁」造成的
    假离线→真开播，以及状态文件短暂丢失后的重复首检。
  - 新作品：key = "post:{sec_uid}:{aweme_id}"，永久不重复（同一作品只推一次）。
    退化计数模式：key = "post:{sec_uid}:count:{count}"，永久不重复。

账本本身也由 CI 持久化（git add -f notify_dedup.json），因此跨 run 有效；
即便单次持久化失败，至多只会在冷却窗口后补推一次，不会形成刷屏。
"""

import math
import os
import time
from typing import Any, Dict, Optional

# 复用公共 JSON 读写（原子写，避免半截文件）
try:
    from common import load_json_file, save_json_file
except Exception:  # 允许单独 import / 单测时降级
    import json as _json

    def load_json_file(filepath: str, default: Any = None) -> Any:
        if default is None:
            default = {}
        if not os.path.exists(filepath):
            return default
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return _json.load(f)
        except Exception:
            return default

    def save_json_file(filepath: str, data: Any) -> None:
        tmp = f"{filepath}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, filepath)


REPO_DIR = os.path.dirname(os.path.abspath(__file__))
LEDGER_FILE = os.path.join(REPO_DIR, "notify_dedup.json")

# 直播通知冷却（秒）：2 小时内同一房间的开播通知只发一次（吸收闪烁 / 状态丢失）
LIVE_COOLDOWN_SECONDS = 7200

# 新作品去重：永久（key 已记录则永不重推）。用无穷大冷却表达「永久」。
PERMANENT = math.inf

# 直播 key 的最长留存（秒）：超过该时长的 live: key 可被清理，避免账本无限增长。
LIVE_KEY_TTL_SECONDS = 7 * 24 * 3600

# 账本条目上限（超出后保留最近 N 条）；post: key 永不因裁剪而丢弃。
MAX_ENTRIES = 5000


def _load() -> Dict[str, Any]:
    return load_json_file(LEDGER_FILE, {})


def _save(ledger: Dict[str, Any]) -> None:
    save_json_file(LEDGER_FILE, ledger)


def should_notify(key: str, cooldown: float = LIVE_COOLDOWN_SECONDS,
                  now: Optional[float] = None) -> bool:
    """该 key 当前是否应该推送。

    - 未记录过 → 允许（True）
    - 已记录，且距上次发送 ≥ cooldown → 允许（True）
    - 已记录，且距上次发送 < cooldown（含 cooldown=PERMANENT 的永久模式）→ 拒绝（False）

    Args:
        key: 去重键（见模块 docstring 的命名约定）
        cooldown: 冷却秒数；传 PERMANENT（math.inf）表示永久不重复
        now: 可注入的当前时间戳（测试用）
    """
    if not key:
        return True
    now = now if now is not None else time.time()
    ledger = _load()
    entry = ledger.get(key)
    if not entry:
        return True
    try:
        last_ts = float(entry.get("ts", 0))
    except (ValueError, TypeError, AttributeError):
        return True
    return (now - last_ts) >= cooldown


def record(key: str, now: Optional[float] = None) -> None:
    """推送成功后记录该 key 的发送时间（幂等：已存在则刷新时间戳）。

    仅在推送确实成功时调用，避免「推送失败却已标记去重」导致漏报后无法补推。
    """
    if not key:
        return
    now = now if now is not None else time.time()
    ledger = _load()
    ledger[key] = {"ts": now}
    _save(ledger)


def prune(now: Optional[float] = None) -> None:
    """裁剪账本：

    - 丢弃过期的 live: key（距上次发送超过 LIVE_KEY_TTL_SECONDS）；
    - post: key 永久保留（同一作品只推一次，绝不能因裁剪而重推）；
    - 若仍超过 MAX_ENTRIES，保留最近 N 条。
    """
    now = now if now is not None else time.time()
    ledger = _load()
    if not ledger:
        return

    kept: Dict[str, Any] = {}
    for k, v in ledger.items():
        if k.startswith("live:"):
            try:
                ts = float(v.get("ts", 0))
            except (ValueError, TypeError, AttributeError):
                ts = 0.0
            if (now - ts) < LIVE_KEY_TTL_SECONDS:
                kept[k] = v
            # 过期 live: key 直接丢弃
        else:
            # post: 等其它 key 永久保留
            kept[k] = v

    if len(kept) > MAX_ENTRIES:
        items = sorted(kept.items(), key=lambda kv: kv[1].get("ts", 0))
        kept = dict(items[-MAX_ENTRIES:])

    if len(kept) != len(ledger):
        _save(kept)
